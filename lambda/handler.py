"""Lambda acionada por upload no bucket de entrada.

Para cada imagem recebida: gera uma miniatura (máx. 512 px) em tons de cinza
e grava o resultado no bucket de saída.
"""
import io
import os
import urllib.parse

import boto3
from PIL import Image, ImageOps

# Dentro do LocalStack, a variável AWS_ENDPOINT_URL é injetada automaticamente,
# então o mesmo código funciona na AWS real sem alteração.
s3 = boto3.client("s3")

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
MAX_SIZE = int(os.environ.get("MAX_SIZE", "512"))
FORMATOS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF"}


def processar(dados: bytes, formato: str) -> bytes:
    img = Image.open(io.BytesIO(dados))
    img = ImageOps.exif_transpose(img)   # respeita a rotação da foto
    img.thumbnail((MAX_SIZE, MAX_SIZE))  # reduz mantendo a proporção
    img = ImageOps.grayscale(img)
    saida = io.BytesIO()
    img.save(saida, format=formato)
    return saida.getvalue()


def lambda_handler(event, context):
    resultados = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        chave = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        ext = os.path.splitext(chave)[1].lower()

        if ext not in FORMATOS:
            print(f"Ignorado (não é imagem): {chave}")
            continue

        obj = s3.get_object(Bucket=bucket, Key=chave)
        resultado = processar(obj["Body"].read(), FORMATOS[ext])

        destino = f"processado/{chave}"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=destino,
            Body=resultado,
            ContentType=obj.get("ContentType", "application/octet-stream"),
        )
        print(f"OK: s3://{bucket}/{chave} -> s3://{OUTPUT_BUCKET}/{destino}")
        resultados.append(destino)

    return {"processados": resultados}
