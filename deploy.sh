#!/usr/bin/env bash
# Empacota e publica a Lambda no LocalStack e liga o bucket de entrada a ela.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$PWD/.venv/bin:$PATH"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1

ENTRADA=imagens-entrada
SAIDA=imagens-saida
FUNCAO=processa-imagem

echo ">> 1/5 Empacotando a Lambda (código + Pillow para Linux x86_64 / Python 3.12)"
rm -rf build function.zip && mkdir build
pip install -q --target build --platform manylinux_2_28_x86_64 \
    --implementation cp --python-version 3.12 --only-binary=:all: pillow
cp lambda/handler.py build/
python3 -c "import shutil; shutil.make_archive('function', 'zip', 'build')"

echo ">> 2/5 Criando os buckets"
awslocal s3 mb s3://$ENTRADA 2>/dev/null || true
awslocal s3 mb s3://$SAIDA   2>/dev/null || true

echo ">> 3/5 Criando a função Lambda"
awslocal lambda delete-function --function-name $FUNCAO 2>/dev/null || true
awslocal lambda create-function \
    --function-name $FUNCAO \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --zip-file fileb://function.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 30 --memory-size 256 \
    --environment "Variables={OUTPUT_BUCKET=$SAIDA,MAX_SIZE=512}" >/dev/null
awslocal lambda wait function-active-v2 --function-name $FUNCAO

echo ">> 4/5 Permitindo que o S3 invoque a função"
awslocal lambda add-permission \
    --function-name $FUNCAO --statement-id s3-invoke \
    --action lambda:InvokeFunction --principal s3.amazonaws.com \
    --source-arn arn:aws:s3:::$ENTRADA >/dev/null

echo ">> 5/5 Configurando a notificação do bucket (ObjectCreated -> Lambda)"
ARN=$(awslocal lambda get-function --function-name $FUNCAO --query 'Configuration.FunctionArn' --output text)
awslocal s3api put-bucket-notification-configuration --bucket $ENTRADA \
    --notification-configuration "{\"LambdaFunctionConfigurations\":[{\"LambdaFunctionArn\":\"$ARN\",\"Events\":[\"s3:ObjectCreated:*\"]}]}"

echo "Pronto! Envie uma imagem para s3://$ENTRADA e veja o resultado em s3://$SAIDA/processado/"
