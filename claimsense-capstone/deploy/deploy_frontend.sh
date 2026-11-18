#!/usr/bin/env bash
# Deploy the review portal to S3 + CloudFront.  Usage: deploy/deploy_frontend.sh <bucket-name> [region]
set -euo pipefail
BUCKET=${1:?usage: deploy/deploy_frontend.sh <globally-unique-bucket-name> [region]}
REGION=${2:-us-east-1}
cd "$(dirname "$0")/.."
python3 frontend/build_data.py
aws cloudformation deploy --region "$REGION" --stack-name claimsense-portal \
  --template-file deploy/frontend.yaml --parameter-overrides BucketName="$BUCKET"
aws s3 sync frontend/ "s3://$BUCKET/" --region "$REGION" --delete --exclude "build_data.py" --exclude "*.pyc"
DIST=$(aws cloudformation describe-stacks --region "$REGION" --stack-name claimsense-portal \
  --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" >/dev/null
aws cloudformation describe-stacks --region "$REGION" --stack-name claimsense-portal \
  --query "Stacks[0].Outputs[?OutputKey=='PortalUrl'].OutputValue" --output text
