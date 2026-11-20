"""Testes da Lambda com o S3 simulado em memória (moto)."""
import importlib
import io
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))

ENTRADA, SAIDA = "imagens-entrada", "imagens-saida"


def evento(chave, bucket=ENTRADA):
    """Evento no mesmo formato que o S3 envia para a Lambda."""
    return {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                         "s3": {"bucket": {"name": bucket}, "object": {"key": chave}}}]}


def imagem(fmt="PNG", tamanho=(1600, 1000), cor=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("OUTPUT_BUCKET", SAIDA)
    monkeypatch.setenv("MAX_SIZE", "512")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=ENTRADA)
        s3.create_bucket(Bucket=SAIDA)
        import handler
        importlib.reload(handler)  # recria o client dentro do mock
        yield s3, handler


def baixar(s3, chave):
    return Image.open(io.BytesIO(s3.get_object(Bucket=SAIDA, Key=chave)["Body"].read()))


def test_png_vira_miniatura_cinza(ambiente):
    s3, handler = ambiente
    s3.put_object(Bucket=ENTRADA, Key="foto.png", Body=imagem("PNG"))

    r = handler.lambda_handler(evento("foto.png"), None)

    assert r == {"processados": ["processado/foto.png"]}
    out = baixar(s3, "processado/foto.png")
    assert out.size == (512, 320)      # proporção 16:10 mantida
    assert out.mode == "L"             # tons de cinza
    assert out.format == "PNG"


def test_jpeg_mantem_formato(ambiente):
    s3, handler = ambiente
    s3.put_object(Bucket=ENTRADA, Key="foto.JPG", Body=imagem("JPEG", (800, 1200)))

    handler.lambda_handler(evento("foto.JPG"), None)

    out = baixar(s3, "processado/foto.JPG")
    assert out.format == "JPEG"
    assert out.size == (341, 512)      # retrato: limita a altura


def test_imagem_pequena_nao_e_ampliada(ambiente):
    s3, handler = ambiente
    s3.put_object(Bucket=ENTRADA, Key="mini.png", Body=imagem("PNG", (100, 50)))

    handler.lambda_handler(evento("mini.png"), None)

    assert baixar(s3, "processado/mini.png").size == (100, 50)


def test_chave_com_espaco_e_acento_url_encoded(ambiente):
    s3, handler = ambiente
    chave = "férias 2026/praia boa.png"
    s3.put_object(Bucket=ENTRADA, Key=chave, Body=imagem())

    # o S3 envia a chave codificada no evento (espaço vira "+")
    handler.lambda_handler(evento("f%C3%A9rias+2026/praia+boa.png"), None)

    assert baixar(s3, f"processado/{chave}").mode == "L"


def test_arquivo_que_nao_e_imagem_e_ignorado(ambiente):
    s3, handler = ambiente
    s3.put_object(Bucket=ENTRADA, Key="notas.txt", Body=b"oi")

    r = handler.lambda_handler(evento("notas.txt"), None)

    assert r == {"processados": []}
    assert "Contents" not in s3.list_objects_v2(Bucket=SAIDA)


def test_varios_registros_no_mesmo_evento(ambiente):
    s3, handler = ambiente
    for nome in ("a.png", "b.png"):
        s3.put_object(Bucket=ENTRADA, Key=nome, Body=imagem())
    ev = {"Records": evento("a.png")["Records"] + evento("b.png")["Records"]}

    r = handler.lambda_handler(ev, None)

    assert r["processados"] == ["processado/a.png", "processado/b.png"]


def test_nao_grava_no_bucket_de_entrada(ambiente):
    """Evita loop infinito: o resultado nunca volta para o bucket que dispara a Lambda."""
    s3, handler = ambiente
    s3.put_object(Bucket=ENTRADA, Key="foto.png", Body=imagem())

    handler.lambda_handler(evento("foto.png"), None)

    chaves = [o["Key"] for o in s3.list_objects_v2(Bucket=ENTRADA)["Contents"]]
    assert chaves == ["foto.png"]


def test_respeita_rotacao_exif(ambiente):
    """Foto de celular 'deitada' com tag EXIF de rotação deve sair em pé."""
    s3, handler = ambiente
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation = girar 90°
    Image.new("RGB", (1000, 500)).save(buf, format="JPEG", exif=exif)
    s3.put_object(Bucket=ENTRADA, Key="cel.jpg", Body=buf.getvalue())

    handler.lambda_handler(evento("cel.jpg"), None)

    assert baixar(s3, "processado/cel.jpg").size == (256, 512)
