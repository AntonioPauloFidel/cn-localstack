#!/usr/bin/env bash
# Envia uma imagem para o bucket de entrada e espera o resultado no bucket de saída.
# Uso: ./test.sh [caminho/da/imagem.jpg]   (sem argumento, gera uma imagem de teste)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:$PATH"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
# Mesmo padrão do slide: aws-cli apontando para o endpoint do LocalStack
AWS="aws --endpoint-url=${ENDPOINT:-http://localhost:4566}"

IMG=${1:-}
if [ -z "$IMG" ]; then
    IMG=exemplos/teste.png
    mkdir -p exemplos
    python3 -c "
from PIL import Image
img = Image.new('RGB', (1600, 1000))
for x in range(1600):
    for y in range(0, 1000, 4):
        img.putpixel((x, y), (x % 256, y % 256, 180))
img.save('$IMG')"
    echo "Imagem de teste gerada: $IMG (1600x1000 colorida)"
fi

NOME=$(basename "$IMG")
echo ">> Enviando $NOME para s3://imagens-entrada"
$AWS s3 cp "$IMG" "s3://imagens-entrada/$NOME"

echo ">> Aguardando a Lambda processar..."
for i in $(seq 1 30); do
    if $AWS s3api head-object --bucket imagens-saida --key "processado/$NOME" >/dev/null 2>&1; then
        mkdir -p resultado
        $AWS s3 cp "s3://imagens-saida/processado/$NOME" "resultado/$NOME" >/dev/null
        echo "OK! Resultado baixado em resultado/$NOME"
        python3 -c "from PIL import Image; a=Image.open('$IMG'); b=Image.open('resultado/$NOME'); print(f'Original: {a.size} {a.mode}  ->  Processada: {b.size} {b.mode}')"
        exit 0
    fi
    sleep 2
done
echo "Tempo esgotado. Veja os logs: docker compose logs localstack | tail -50"
exit 1
