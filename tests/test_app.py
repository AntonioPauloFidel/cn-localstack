"""Testes do app web com S3 e DynamoDB simulados em memória (moto)."""
import importlib
import io
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

BUCKET = "imagens-entrada"
TABELA = "usuarios"


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=BUCKET)
        dynamo = boto3.client("dynamodb")
        dynamo.create_table(
            TableName=TABELA,
            AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        import app as modulo
        importlib.reload(modulo)
        modulo.app.config["TESTING"] = True
        yield modulo.app, s3, boto3.resource("dynamodb").Table(TABELA)


@pytest.fixture
def cliente(ambiente):
    app, s3, _ = ambiente
    return app.test_client(), s3


@pytest.fixture
def logado(cliente):
    c, s3 = cliente
    cadastrar(c)
    entrar(c)
    return c, s3


def cadastrar(c, nome="Ana", email="ana@ulbra.br", senha="segredo123"):
    return c.post("/cadastro", data={"nome": nome, "email": email, "senha": senha},
                  follow_redirects=True)


def entrar(c, email="ana@ulbra.br", senha="segredo123"):
    return c.post("/login", data={"email": email, "senha": senha}, follow_redirects=True)


def enviar(c, nome="foto.png", conteudo=b"\x89PNG fake"):
    return c.post("/upload", data={"arquivo": (io.BytesIO(conteudo), nome)},
                  content_type="multipart/form-data", follow_redirects=True)


def chaves(s3):
    return [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


# ---------- Atividade 2: contas no DynamoDB ----------

def test_cadastro_grava_no_dynamodb_com_senha_criptografada(ambiente):
    app, _, tabela = ambiente
    r = cadastrar(app.test_client(), email="Ana@ULBRA.br")
    assert "Conta criada" in r.get_data(as_text=True)

    item = tabela.get_item(Key={"email": "ana@ulbra.br"})["Item"]  # e-mail normalizado
    assert item["nome"] == "Ana"
    assert item["senha_hash"] != "segredo123"
    assert item["senha_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_nao_permite_email_duplicado(ambiente):
    app, _, tabela = ambiente
    c = app.test_client()
    cadastrar(c, nome="Ana")
    r = cadastrar(c, nome="Impostor", senha="outrasenha")
    assert "Já existe uma conta" in r.get_data(as_text=True)
    assert tabela.get_item(Key={"email": "ana@ulbra.br"})["Item"]["nome"] == "Ana"


@pytest.mark.parametrize("dados, erro", [
    ({"nome": "", "email": "a@b.com", "senha": "123456"}, "Informe nome"),
    ({"nome": "Ana", "email": "invalido", "senha": "123456"}, "Informe nome"),
    ({"nome": "Ana", "email": "a@b.com", "senha": "123"}, "pelo menos 6"),
])
def test_cadastro_valida_campos(cliente, dados, erro):
    c, _ = cliente
    r = c.post("/cadastro", data=dados)
    assert erro in r.get_data(as_text=True)


def test_login_com_sucesso_mostra_nome(cliente):
    c, _ = cliente
    cadastrar(c)
    r = entrar(c)
    assert "Olá, <strong>Ana</strong>" in r.get_data(as_text=True)


@pytest.mark.parametrize("email, senha", [
    ("ana@ulbra.br", "senhaerrada"),
    ("ninguem@ulbra.br", "segredo123"),
])
def test_login_invalido_mesma_mensagem(cliente, email, senha):
    c, _ = cliente
    cadastrar(c)
    r = entrar(c, email, senha)
    html = r.get_data(as_text=True)
    assert "E-mail ou senha inválidos" in html
    assert "Olá" not in html


def test_logout_encerra_sessao(logado):
    c, _ = logado
    c.post("/logout")
    assert c.get("/").status_code == 302


@pytest.mark.parametrize("metodo, rota", [
    ("get", "/"), ("post", "/upload"), ("get", "/download/foto.png"),
])
def test_rotas_exigem_login(cliente, metodo, rota):
    c, _ = cliente
    r = getattr(c, metodo)(rota)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# ---------- Atividade 1: upload, listagem e download no S3 ----------

def test_pagina_inicial_vazia(logado):
    c, _ = logado
    assert "Nenhuma imagem ainda" in c.get("/").get_data(as_text=True)


def test_upload_grava_na_pasta_do_usuario_e_aparece_na_lista(logado):
    c, s3 = logado
    html = enviar(c, "foto.png").get_data(as_text=True)
    assert "foto.png enviado!" in html
    assert "foto.png" in html
    [chave] = chaves(s3)
    assert chave.startswith("usuarios/") and chave.endswith("/foto.png")


def test_download_devolve_o_mesmo_conteudo(logado):
    c, _ = logado
    enviar(c, "foto.png", b"conteudo-da-imagem")
    r = c.get("/download/foto.png")
    assert r.status_code == 200
    assert r.data == b"conteudo-da-imagem"
    assert "attachment" in r.headers["Content-Disposition"]


def test_download_inexistente_da_404(logado):
    c, _ = logado
    assert c.get("/download/nao-existe.png").status_code == 404


def test_rejeita_arquivo_que_nao_e_imagem(logado):
    c, s3 = logado
    assert "Envie uma imagem" in enviar(c, "virus.exe").get_data(as_text=True)
    assert chaves(s3) == []


def test_nome_perigoso_e_sanitizado(logado):
    c, s3 = logado
    enviar(c, "../../etc/foto.png")
    assert chaves(s3)[0].endswith("/etc_foto.png")


# ---------- Integração 1 + 2: isolamento entre usuários ----------

def test_usuario_nao_ve_nem_baixa_imagem_de_outro(ambiente):
    app, s3, _ = ambiente
    ana, bia = app.test_client(), app.test_client()
    cadastrar(ana); entrar(ana)
    cadastrar(bia, nome="Bia", email="bia@ulbra.br"); entrar(bia, "bia@ulbra.br")

    enviar(ana, "segredo-da-ana.png", b"privado")

    assert "segredo-da-ana.png" not in bia.get("/").get_data(as_text=True)
    assert bia.get("/download/segredo-da-ana.png").status_code == 404
    chave_ana = chaves(s3)[0]
    assert bia.get(f"/download/../../{chave_ana}").status_code == 404
