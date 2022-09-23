.PHONY: run_local run_docker install test_local build test

install:
	poetry install
	poetry run pre-commit install
	poetry run playwright install 
	poetry run pip install "git+https://github.com/facebookresearch/detectron2.git@v0.5#egg=detectron2"
	cp .env.example .env

run_local:
	LAYOUTPARSER_MODEL=faster_rcnn_R_50_FPN_3x PDF_OCR_AGENT=tesseract TARGET_LANGUAGES=en GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-creds.json python -m cli.run_parser ./data/raw ./data/processed

test_local:
	LAYOUTPARSER_MODEL=faster_rcnn_R_50_FPN_3x PDF_OCR_AGENT=tesseract TARGET_LANGUAGES=en python -m pytest

build:
	cp Dockerfile.local.example Dockerfile
	docker build -t html-parser .

test:
	docker run -e "LAYOUTPARSER_MODEL=faster_rcnn_R_50_FPN_3x" -e "PDF_OCR_AGENT=tesseract" --network host html-parser python -m pytest -vvv

run_docker:
	docker run --network host -v ${PWD}/data:/app/data html-parser python -m cli.run_parser ./data/raw ./data/processed

run_local_against_s3:
	cp Dockerfile.aws.example Dockerfile
	docker build -t html-parser_s3 .
	docker run -e s3_in=s3://data-pipeline-a64047a/runs/09-21-2022_14:33___516c0c8e-6c66-44b7-8682-b56469757736/loader_output_small/ -e s3_out=s3://data-pipeline-a64047a/runs/09-21-2022_14:33___516c0c8e-6c66-44b7-8682-b56469757736/parser_output/ -it html-parser_s3

build_and_push_ecr:
	cp Dockerfile.aws.example Dockerfile
	aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 281621126254.dkr.ecr.us-east-1.amazonaws.com
	docker build -t parser-2263e83 .
	docker tag parser-2263e83:latest 281621126254.dkr.ecr.us-east-1.amazonaws.com/parser-2263e83:latest
	docker push 281621126254.dkr.ecr.us-east-1.amazonaws.com/parser-2263e83:latest	