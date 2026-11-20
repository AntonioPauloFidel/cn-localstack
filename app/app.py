"""Galeria de imagens na "nuvem" (LocalStack).

Atividade 1 — upload, listagem e download de imagens no S3.
Atividade 2 — contas de usuário no DynamoDB; cada usuário vê só as próprias imagens.
Atividade 3 — o upload dispara uma Lambda (S3 -> Lambda) que gera a versão processada
              no bucket de saída; a galeria mostra e permite baixar o resultado.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from functools import wraps

import boto3
from botocore.exceptions import ClientError
from flask import (Flask, Response, abort, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BUCKET = os.environ.get("BUCKET_ENTRADA", "imagens-entrada")
BUCKET_SAIDA = os.environ.get("BUCKET_SAIDA", "imagens-saida")
PREFIXO_SAIDA = "processado/"  # onde a Lambda grava o resultado
TABELA = os.environ.get("TABELA_USUARIOS", "usuarios")
EXTENSOES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-troque-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB por upload


# O endpoint vem de AWS_ENDPOINT_URL (LocalStack); sem ela, fala com a AWS real.
def s3():
    return boto3.client("s3")


def usuarios():
    return boto3.resource("dynamodb").Table(TABELA)


def login_obrigatorio(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Entre na sua conta para continuar.", "erro")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def prefixo():
    """Pasta do usuário logado no bucket: cada um só enxerga a sua."""
    return f"usuarios/{session['usuario_id']}/"


# ---------- Contas (DynamoDB) ----------

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        if not nome or not EMAIL_RE.match(email):
            flash("Informe nome e um e-mail válido.", "erro")
        elif len(senha) < 6:
            flash("A senha precisa ter pelo menos 6 caracteres.", "erro")
        else:
            try:
                usuarios().put_item(
                    Item={
                        "email": email,
                        "id": uuid.uuid4().hex,
                        "nome": nome,
                        "senha_hash": generate_password_hash(senha),  # nunca a senha pura
                        "criado_em": datetime.now(timezone.utc).isoformat(),
                    },
                    # não sobrescreve conta existente
                    ConditionExpression="attribute_not_exists(email)",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
                flash("Já existe uma conta com esse e-mail.", "erro")
            else:
                flash("Conta criada! Agora é só entrar.", "ok")
                return redirect(url_for("login"))
    return render_template("cadastro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        item = usuarios().get_item(Key={"email": email}).get("Item")

        # mesma mensagem para e-mail inexistente e senha errada (não revela quem tem conta)
        if not item or not check_password_hash(item["senha_hash"], senha):
            flash("E-mail ou senha inválidos.", "erro")
        else:
            session.clear()
            session.update(usuario_id=item["id"], nome=item["nome"], email=item["email"])
            return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Imagens (S3) ----------

@app.get("/")
@login_obrigatorio
def index():
    resp = s3().list_objects_v2(Bucket=BUCKET, Prefix=prefixo())
    arquivos = sorted(resp.get("Contents", []), key=lambda o: o["LastModified"], reverse=True)
    # Atividade 3: quais já foram processados pela Lambda?
    saida = s3().list_objects_v2(Bucket=BUCKET_SAIDA, Prefix=PREFIXO_SAIDA + prefixo())
    prontos = {o["Key"][len(PREFIXO_SAIDA + prefixo()):] for o in saida.get("Contents", [])}
    for a in arquivos:
        a["Nome"] = a["Key"][len(prefixo()):]
        a["Processada"] = a["Nome"] in prontos
    pendentes = any(not a["Processada"] for a in arquivos)
    return render_template("index.html", arquivos=arquivos, pendentes=pendentes)


@app.post("/upload")
@login_obrigatorio
def upload():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo.", "erro")
        return redirect(url_for("index"))

    nome = secure_filename(arquivo.filename)
    if os.path.splitext(nome)[1].lower() not in EXTENSOES:
        flash("Envie uma imagem (jpg, png, gif ou webp).", "erro")
        return redirect(url_for("index"))

    s3().upload_fileobj(arquivo, BUCKET, prefixo() + nome,
                        ExtraArgs={"ContentType": arquivo.mimetype or "application/octet-stream"})
    flash(f"{nome} enviado!", "ok")
    return redirect(url_for("index"))


@app.get("/download/<path:nome>")
@login_obrigatorio
def download(nome):
    return enviar_objeto(BUCKET, prefixo() + nome, nome, anexo=True)


@app.get("/processada/<path:nome>")
@login_obrigatorio
def processada(nome):
    """Atividade 3: resultado gerado pela Lambda (inline para a miniatura, ou ?baixar=1)."""
    anexo = request.args.get("baixar") == "1"
    return enviar_objeto(BUCKET_SAIDA, PREFIXO_SAIDA + prefixo() + nome,
                         f"processada-{nome}", anexo=anexo)


def enviar_objeto(bucket, chave, nome_arquivo, anexo):
    try:
        obj = s3().get_object(Bucket=bucket, Key=chave)
    except ClientError:
        abort(404)
    disposicao = "attachment" if anexo else "inline"
    return Response(obj["Body"].iter_chunks(), mimetype=obj.get("ContentType"),
                    headers={"Content-Disposition": f'{disposicao}; filename="{nome_arquivo}"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
