#!/usr/bin/env bash
# Cria toda a infraestrutura no LocalStack, na ordem em que as atividades evoluem.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:$PATH"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
# Mesmo padrão do slide: aws-cli apontando para o endpoint do LocalStack
AWS="aws --endpoint-url=${ENDPOINT:-http://localhost:4566}"

ENTRADA=imagens-entrada
SAIDA=imagens-saida
TABELA=usuarios
FUNCAO=processa-imagem

# ---------------- Atividade 1: S3 ----------------
echo ">> [Atividade 1] Criando os buckets"
$AWS s3 mb s3://$ENTRADA >/dev/null 2>&1 || true
$AWS s3 mb s3://$SAIDA   >/dev/null 2>&1 || true

# ---------------- Atividade 2: DynamoDB ----------------
echo ">> [Atividade 2] Criando a tabela de usuários (chave: email)"
if ! $AWS dynamodb describe-table --table-name $TABELA >/dev/null 2>&1; then
    $AWS dynamodb create-table --table-name $TABELA \
        --attribute-definitions AttributeName=email,AttributeType=S \
        --key-schema AttributeName=email,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST >/dev/null
    $AWS dynamodb wait table-exists --table-name $TABELA
fi

# ---------------- Atividade 3: Lambda ----------------
echo ">> [Atividade 3] Empacotando a Lambda (código + Pillow para Linux x86_64 / Python 3.12)"
rm -rf build function.zip && mkdir build
pip install -q --target build --platform manylinux_2_28_x86_64 \
    --implementation cp --python-version 3.12 --only-binary=:all: pillow
cp lambda/handler.py build/
python3 -c "import shutil; shutil.make_archive('function', 'zip', 'build')"

echo ">> [Atividade 3] Criando a função Lambda"
$AWS lambda delete-function --function-name $FUNCAO >/dev/null 2>&1 || true
$AWS lambda create-function \
    --function-name $FUNCAO \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --zip-file fileb://function.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 30 --memory-size 256 \
    --environment "Variables={OUTPUT_BUCKET=$SAIDA,MAX_SIZE=512}" >/dev/null
$AWS lambda wait function-active-v2 --function-name $FUNCAO

echo ">> [Atividade 3] Permitindo que o S3 invoque a função"
$AWS lambda add-permission \
    --function-name $FUNCAO --statement-id s3-invoke \
    --action lambda:InvokeFunction --principal s3.amazonaws.com \
    --source-arn arn:aws:s3:::$ENTRADA >/dev/null

echo ">> [Atividade 3] Gatilho: upload em $ENTRADA (ObjectCreated) -> Lambda"
ARN=$($AWS lambda get-function --function-name $FUNCAO --query 'Configuration.FunctionArn' --output text)
$AWS s3api put-bucket-notification-configuration --bucket $ENTRADA \
    --notification-configuration "{\"LambdaFunctionConfigurations\":[{\"LambdaFunctionArn\":\"$ARN\",\"Events\":[\"s3:ObjectCreated:*\"]}]}"

echo "Pronto! Acesse http://localhost:5000"
