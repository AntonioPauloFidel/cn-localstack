"""Testes do app web com S3 simulado em memória (moto)."""
import importlib
import io
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

BUCKET = "imagens-entrada"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=BUCKET)
        import app as modulo
        importlib.reload(modulo)
        modulo.app.config["TESTING"] = True
        yield modulo.app.test_client(), s3


def enviar(c, nome="foto.png", conteudo=b"\x89PNG fake"):
    return c.post("/upload", data={"arquivo": (io.BytesIO(conteudo), nome)},
                  content_type="multipart/form-data", follow_redirects=True)


def test_pagina_inicial_vazia(cliente):
    c, _ = cliente
    r = c.get("/")
    assert r.status_code == 200
    assert "Nenhuma imagem ainda" in r.get_data(as_text=True)


def test_upload_grava_no_s3_e_aparece_na_lista(cliente):
    c, s3 = cliente
    r = enviar(c, "foto.png")
    html = r.get_data(as_text=True)
    assert "foto.png enviado!" in html
    assert "foto.png" in html
    assert s3.get_object(Bucket=BUCKET, Key="foto.png")["Body"].read() == b"\x89PNG fake"


def test_download_devolve_o_mesmo_conteudo(cliente):
    c, _ = cliente
    enviar(c, "foto.png", b"conteudo-da-imagem")
    r = c.get("/download/foto.png")
    assert r.status_code == 200
    assert r.data == b"conteudo-da-imagem"
    assert "attachment" in r.headers["Content-Disposition"]


def test_download_inexistente_da_404(cliente):
    c, _ = cliente
    assert c.get("/download/nao-existe.png").status_code == 404


def test_rejeita_arquivo_que_nao_e_imagem(cliente):
    c, s3 = cliente
    r = enviar(c, "virus.exe")
    assert "Envie uma imagem" in r.get_data(as_text=True)
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)


def test_nome_perigoso_e_sanitizado(cliente):
    c, s3 = cliente
    enviar(c, "../../etc/foto.png")
    chaves = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert chaves == ["etc_foto.png"]
