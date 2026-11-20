"""Atividade 1 — upload, listagem e download de imagens no S3 (LocalStack)."""
import os

import boto3
from botocore.exceptions import ClientError
from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

BUCKET = os.environ.get("BUCKET_ENTRADA", "imagens-entrada")
EXTENSOES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-troque-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB por upload


def s3():
    # O endpoint vem de AWS_ENDPOINT_URL (LocalStack); sem ela, fala com a AWS real.
    return boto3.client("s3")


@app.get("/")
def index():
    resp = s3().list_objects_v2(Bucket=BUCKET)
    arquivos = sorted(resp.get("Contents", []), key=lambda o: o["LastModified"], reverse=True)
    return render_template("index.html", arquivos=arquivos)


@app.post("/upload")
def upload():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo.", "erro")
        return redirect(url_for("index"))

    nome = secure_filename(arquivo.filename)
    if os.path.splitext(nome)[1].lower() not in EXTENSOES:
        flash("Envie uma imagem (jpg, png, gif ou webp).", "erro")
        return redirect(url_for("index"))

    s3().upload_fileobj(arquivo, BUCKET, nome,
                        ExtraArgs={"ContentType": arquivo.mimetype or "application/octet-stream"})
    flash(f"{nome} enviado!", "ok")
    return redirect(url_for("index"))


@app.get("/download/<path:chave>")
def download(chave):
    try:
        obj = s3().get_object(Bucket=BUCKET, Key=chave)
    except ClientError:
        abort(404)
    nome = chave.rsplit("/", 1)[-1]
    return Response(obj["Body"].iter_chunks(), mimetype=obj.get("ContentType"),
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
