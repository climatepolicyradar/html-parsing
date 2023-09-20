import re
import tempfile
from pathlib import Path
from typing import Sequence, Union
from unittest import mock
import json

import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from click.testing import CliRunner
from cloudpathlib.local import LocalS3Path
from cpr_data_access.parser_models import (
    ParserOutput,
    HTMLData,
    CONTENT_TYPE_HTML,
    CONTENT_TYPE_PDF,
)
from cpr_data_access.pipeline_general_models import BackendDocument
from azure.ai.formrecognizer import AnalyzeResult
from mock import patch

from cli.run_parser import main as cli_main
from cli.translate_outputs import should_be_translated, identify_translation_languages
from src.base import PARSER_METADATA_KEY
from src.config import TARGET_LANGUAGES

patcher = mock.patch(
    "src.translator.translate.translate_text",
    mock.MagicMock(return_value=["translated text"]),
)
patcher.start()


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_local_parallel(
    test_input_dir, expected_pipeline_metadata_keys
) -> None:
    """Test that the parsing CLI runs and outputs a file."""
    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()

        result = runner.invoke(
            cli_main, [str(test_input_dir), output_dir, "--parallel"]
        )

        assert result.exit_code == 0

        # Default config is to translate to English, and the HTML doc is already in
        # English - so we just expect a translation of the PDF
        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json",
            Path(output_dir) / "test_pdf.json",
            Path(output_dir) / "test_no_content_type.json",
            Path(output_dir) / "test_pdf_translated_en.json",
        }

        for output_file in Path(output_dir).glob("*.json"):
            parser_output = ParserOutput.parse_file(output_file)
            assert isinstance(parser_output, ParserOutput)

            if parser_output.document_content_type == CONTENT_TYPE_HTML:
                assert parser_output.html_data.text_blocks not in [[], None]

            if parser_output.document_content_type == CONTENT_TYPE_PDF:
                assert parser_output.pdf_data.text_blocks not in [[], None]
                assert parser_output.pdf_data.md5sum != ""
                assert parser_output.pdf_data.page_metadata not in [[], None]
                assert PARSER_METADATA_KEY in parser_output.pipeline_metadata.keys()
                assert (
                    set(parser_output.pipeline_metadata[PARSER_METADATA_KEY].keys())
                    == expected_pipeline_metadata_keys
                )

                # Test that we can call the vertically_flip_text_block_coords method
                # on the ParserOutput, this will assert that the page numbers are
                # correct as well.
                parser_output.vertically_flip_text_block_coords().get_text_blocks()


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_local_series(test_input_dir) -> None:
    """Test that the parsing CLI runs and outputs a file."""
    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()

        result = runner.invoke(cli_main, [str(test_input_dir), output_dir])

        assert result.exit_code == 0

        # Default config is to translate to English, and the HTML doc is already in
        # English - so we just expect a translation of the PDF
        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json",
            Path(output_dir) / "test_pdf.json",
            Path(output_dir) / "test_no_content_type.json",
            Path(output_dir) / "test_pdf_translated_en.json",
        }

        for output_file in Path(output_dir).glob("*.json"):
            parser_output = ParserOutput.parse_file(output_file)
            assert isinstance(parser_output, ParserOutput)

            if parser_output.document_content_type == CONTENT_TYPE_HTML:
                assert parser_output.html_data.text_blocks not in [[], None]

            if parser_output.document_content_type == CONTENT_TYPE_PDF:
                assert parser_output.pdf_data.text_blocks not in [[], None]
                assert parser_output.pdf_data.md5sum != ""
                assert parser_output.pdf_data.page_metadata not in [[], None]


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_cache_azure_response_local(
    test_input_dir, test_azure_api_response_dir, archived_file_name_pattern
) -> None:
    """Test that the parser can successfully save api responses locally."""
    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()

        result = runner.invoke(
            cli_main,
            [
                str(test_input_dir),
                output_dir,
                "--azure_api_response_cache_dir",
                test_azure_api_response_dir,
            ],
        )

        assert result.exit_code == 0

        # Default config is to translate to English, and the HTML doc is already in
        # English - so we just expect a translation of the PDF
        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json",
            Path(output_dir) / "test_pdf.json",
            Path(output_dir) / "test_no_content_type.json",
            Path(output_dir) / "test_pdf_translated_en.json",
        }

        for output_file in Path(output_dir).glob("*.json"):
            parser_output = ParserOutput.parse_file(output_file)
            assert isinstance(parser_output, ParserOutput)

            if parser_output.document_content_type == CONTENT_TYPE_HTML:
                assert parser_output.html_data.text_blocks not in [[], None]

            if parser_output.document_content_type == CONTENT_TYPE_PDF:
                assert parser_output.pdf_data.text_blocks not in [[], None]
                assert parser_output.pdf_data.md5sum != ""
                assert parser_output.pdf_data.page_metadata not in [[], None]

        azure_responses = set(Path(test_azure_api_response_dir).glob("*/*.json"))
        assert len(azure_responses) == 1
        for file in azure_responses:
            # Check that the object is of the correct structure and has the correct
            # file name

            AnalyzeResult.from_dict(json.loads(file.read_text()))
            assert re.match(archived_file_name_pattern, file.name)


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_cache_azure_response_s3(
    test_input_dir, archived_file_name_pattern
) -> None:
    """Test that the parser can successfully save api responses remotely."""

    input_dir = "s3://test-bucket/test-input-dir"
    output_dir = "s3://test-bucket/test-output-dir"
    azure_cache_prefix = "azure_api_response_cache"
    test_azure_api_response_dir = output_dir + "/" + azure_cache_prefix

    # Copy test data to mock of S3 path
    html_file_path = LocalS3Path(f"{input_dir}/test_html.json")
    html_file_data: str = (test_input_dir / "test_html.json").read_text()
    html_file_path.write_text(html_file_data)

    pdf_file_path = LocalS3Path(f"{input_dir}/test_pdf.json")
    pdf_file_data: str = (test_input_dir / "test_pdf.json").read_text()
    pdf_file_path.write_text(pdf_file_data)

    with mock.patch("cli.run_parser.S3Path", LocalS3Path):
        runner = CliRunner()
        result = runner.invoke(
            cli_main,
            [
                input_dir,
                output_dir,
                "--s3",
                "--parallel",
                "--azure_api_response_cache_dir",
                test_azure_api_response_dir,
            ],
        )
        assert result.exit_code == 0
        assert set(LocalS3Path(output_dir).glob("*.json")) == {
            LocalS3Path(output_dir) / "test_html.json",
            LocalS3Path(output_dir) / "test_pdf.json",
            LocalS3Path(output_dir) / "test_pdf_translated_en.json",
        }

        azure_responses = set(LocalS3Path(test_azure_api_response_dir).glob("*/*.json"))
        assert len(azure_responses) == 1
        for file in azure_responses:
            # Check that the object is of the correct structure and has the correct
            # file name
            AnalyzeResult.from_dict(json.loads(file.read_text()))
            assert re.match(archived_file_name_pattern, file.name)
            assert file.parts[-2] == json.loads(pdf_file_data)["document_id"]
            assert file.parts[-3] == azure_cache_prefix


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_s3(test_input_dir) -> None:
    """Test that the parsing CLI runs and outputs a file."""

    input_dir = "s3://test-bucket/test-input-dir-s3"
    output_dir = "s3://test-bucket/test-output-dir-s3"

    # Copy test data to mock of S3 path
    input_file_path = LocalS3Path(f"{input_dir}/test_html.json")
    input_file_path.write_text((test_input_dir / "test_html.json").read_text())

    with mock.patch("cli.run_parser.S3Path", LocalS3Path):
        runner = CliRunner()
        result = runner.invoke(cli_main, [input_dir, output_dir, "--s3", "--parallel"])
        assert result.exit_code == 0
        assert set(LocalS3Path(output_dir).glob("*.json")) == {
            LocalS3Path(output_dir) / "test_html.json"
        }


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_specific_files() -> None:
    """Test that using the `--files` flag only parses the files that have been specified."""

    input_dir = str((Path(__file__).parent / "test_data" / "input").resolve())

    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()
        result = runner.invoke(
            cli_main, [input_dir, output_dir, "--parallel", "--files", "test_html.json"]
        )

        assert result.exit_code == 0

        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json"
        }


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_run_parser_skip_already_done(backend_document_json, caplog) -> None:
    """Test that files which have already been parsed are skipped by default."""

    input_dir = str((Path(__file__).parent / "test_data" / "input").resolve())

    with tempfile.TemporaryDirectory() as output_dir:
        with open(Path(output_dir) / "test_pdf.json", "w") as f:
            f.write(
                ParserOutput.parse_obj(
                    {
                        "document_id": "test_pdf",
                        "document_metadata": backend_document_json,
                        "document_source_url": "https://www.pdfs.org",
                        "document_cdn_object": "test_pdf.pdf",
                        "document_md5_sum": "abcdefghijk",
                        "document_name": "test_pdf",
                        "document_description": "test_pdf_description",
                        "document_content_type": "application/pdf",
                        "languages": ["en"],
                        "document_slug": "slug",
                        "pdf_data": {
                            "text_blocks": [
                                {
                                    "text": ["hello"],
                                    "text_block_id": "world",
                                    "type": "Text",
                                    "type_confidence": 0.78,
                                    "coords": [],
                                    "page_number": 1,
                                }
                            ],
                            "page_metadata": [],
                            "md5sum": "abcdefg",
                        },
                        "html_data": None,
                    }
                ).json()
            )

        with open(Path(output_dir) / "test_html.json", "w") as f:
            f.write(
                ParserOutput.parse_obj(
                    {
                        "document_id": "test_html",
                        "document_metadata": backend_document_json,
                        "document_source_url": "https://www.google.org",
                        "document_cdn_object": None,
                        "document_md5_sum": None,
                        "document_name": "test_html",
                        "document_description": "test_html_description",
                        "document_content_type": "text/html",
                        "languages": ["en"],
                        "document_slug": "slug",
                        "html_data": {
                            "text_blocks": [
                                {
                                    "text": ["hello"],
                                    "text_block_id": "world",
                                    "type": "Text",
                                    "type_confidence": 0.78,
                                }
                            ],
                            "detected_title": "",
                            "detected_date": None,
                            "has_valid_text": False,
                        },
                        "pdf_data": None,
                    }
                ).json()
            )

        runner = CliRunner()
        result = runner.invoke(
            cli_main,
            [
                input_dir,
                output_dir,
                "--parallel",
            ],
        )

        assert result.exit_code == 0

        assert "Skipping already parsed html document." in caplog.text
        assert "Skipping already parsed pdf." in caplog.text


_target_languages = set(TARGET_LANGUAGES)


def get_parser_output(
    translated: bool,
    source_url: Union[str, None],
    languages: Sequence[str],
    document_metadata: dict,
) -> ParserOutput:
    """Generate the parser output objects for the tests given input variables."""
    return ParserOutput(
        document_id="sdf",
        document_metadata=BackendDocument.parse_obj(document_metadata),
        document_name="sdf",
        document_description="sdf",
        document_source_url=source_url,
        document_cdn_object="sdf",
        document_content_type="text/html",
        document_md5_sum="sdf",
        document_slug="sdf",
        languages=languages,
        translated=translated,
        html_data=HTMLData(
            text_blocks=[],
            detected_date=None,
            detected_title="",
            has_valid_text=False,
        ),
        pdf_data=None,
    )


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_should_be_translated(backend_document_json) -> None:
    """Tests whether we can successfully determine whether to translate a known input documents."""
    doc_1 = get_parser_output(
        translated=False,
        source_url="https://www.google.org",
        languages=["fr"],
        document_metadata=backend_document_json,
    )
    assert should_be_translated(doc_1) is True

    doc_2 = get_parser_output(
        translated=False,
        source_url=None,
        languages=["fr"],
        document_metadata=backend_document_json,
    )
    assert should_be_translated(doc_2) is False

    doc_3 = get_parser_output(
        translated=False,
        source_url="https://www.google.org",
        languages=["English"],
        document_metadata=backend_document_json,
    )
    assert should_be_translated(doc_3) is True

    doc_4 = get_parser_output(
        translated=True,
        source_url="https://www.google.org",
        languages=["fr"],
        document_metadata=backend_document_json,
    )
    assert should_be_translated(doc_4) is False


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_identify_target_languages(backend_document_json) -> None:
    """Tests whether we can successfully determine the target lanugages to translate too for a known input documents."""
    doc_1 = get_parser_output(
        translated=False,
        source_url="https://www.google.org",
        languages=["fr"],
        document_metadata=backend_document_json,
    )
    assert identify_translation_languages(doc_1, _target_languages) == {"en"}

    doc_2 = get_parser_output(
        translated=False,
        source_url="https://www.google.org",
        languages=["en"],
        document_metadata=backend_document_json,
    )
    assert identify_translation_languages(doc_2, _target_languages) == set()


@patch("cli.parse_pdfs.AzureApiWrapper.analyze_document_from_bytes")
def test_fail_safely_on_azure_uncaught_exception(
    mock_get, test_input_dir, caplog
) -> None:
    """
    Test the functionality of the pdf parser.

    Assert that we safely fail pdf parsing using the azure pdf parser should the default
    endpoint fail with an uncaught Exception.
    """
    mock_get.side_effect = Exception(
        mock.Mock(status=500), "Mock Internal Server Error"
    )

    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()

        result = runner.invoke(
            cli_main, [str(test_input_dir), output_dir, "--parallel"]
        )

        assert result.exit_code == 0

        # Default config is to translate to English, and the HTML doc is already in
        # English - so we just expect a translation of the PDF
        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json",
            Path(output_dir) / "test_pdf.json",
            Path(output_dir) / "test_no_content_type.json",
            Path(output_dir) / "test_pdf_translated_en.json",
        }

        for output_file in Path(output_dir).glob("*.json"):
            parser_output = ParserOutput.parse_file(output_file)
            assert isinstance(parser_output, ParserOutput)

            # Any html data should be parsed successfully as it is not using the azure
            # api, but the pdf data should fail due to the uncaught exception as we
            # don't re-attempt with the large document endpoint in this case

            if parser_output.document_content_type == CONTENT_TYPE_HTML:
                assert parser_output.html_data.text_blocks not in [[], None]

            if parser_output.document_content_type == CONTENT_TYPE_PDF:
                assert parser_output.pdf_data.text_blocks in [[], None]
                assert parser_output.pdf_data.md5sum == ""
                assert parser_output.pdf_data.page_metadata in [[], None]


@patch("cli.parse_pdfs.AzureApiWrapper.analyze_document_from_bytes")
def test_fail_safely_on_azure_service_request_error(
    mock_get, test_input_dir, caplog
) -> None:
    """
    Test the functionality of the pdf parser.

    Assert that we safely fail pdf parsing using the azure pdf parser should the default
    endpoint fail with an uncaught Exception.
    """
    mock_get.side_effect = ServiceRequestError(
        response=mock.Mock(status=500), message="Mock Service Request Error"
    )

    with tempfile.TemporaryDirectory() as output_dir:
        runner = CliRunner()

        result = runner.invoke(
            cli_main, [str(test_input_dir), output_dir, "--parallel"]
        )

        assert result.exit_code == 0

        assert (
            "Failed to parse document with Azure API. This is most likely due to "
            "incorrect azure api credentials." in caplog.text
        )

        assert set(Path(output_dir).glob("*.json")) == {
            Path(output_dir) / "test_html.json",
            Path(output_dir) / "test_pdf.json",
            Path(output_dir) / "test_no_content_type.json",
            Path(output_dir) / "test_pdf_translated_en.json",
        }

        for output_file in Path(output_dir).glob("*.json"):
            parser_output = ParserOutput.parse_file(output_file)
            assert isinstance(parser_output, ParserOutput)

            # Any html data should be parsed successfully as it is not using the azure
            # api, but the pdf data should fail due to the service request error as we
            # don't re-attempt with the large document endpoint in this case

            if parser_output.document_content_type == CONTENT_TYPE_HTML:
                assert parser_output.html_data.text_blocks not in [[], None]

            if parser_output.document_content_type == CONTENT_TYPE_PDF:
                assert parser_output.pdf_data.text_blocks in [[], None]
                assert parser_output.pdf_data.md5sum == ""
                assert parser_output.pdf_data.page_metadata in [[], None]


def test_fail_safely_on_azure_http_response_error(
    test_input_dir, one_page_analyse_result, caplog
) -> None:
    """
    Test the functionality of the pdf parser.

    Assert that we retry pdf parsing using the large document endpoint should the default
    endpoint fail with a HttpResponseError.
    """
    with (
        patch(
            "cli.parse_pdfs.AzureApiWrapper.analyze_large_document_from_bytes"
        ) as mock_get_large,
        patch(
            "cli.parse_pdfs.AzureApiWrapper.analyze_document_from_bytes"
        ) as mock_get_default,
    ):
        mock_get_default.side_effect = HttpResponseError(
            response=mock.Mock(status=500), message="Mock Internal Server Error"
        )

        mock_get_large.return_value = ({"0": []}, one_page_analyse_result)

        with tempfile.TemporaryDirectory() as output_dir:
            runner = CliRunner()

            result = runner.invoke(
                cli_main, [str(test_input_dir), output_dir, "--parallel"]
            )

            assert result.exit_code == 0

            assert (
                "Failed to parse document with Azure API with default endpoint, "
                "retrying with large document endpoint." in caplog.text
            )

            assert set(Path(output_dir).glob("*.json")) == {
                Path(output_dir) / "test_html.json",
                Path(output_dir) / "test_pdf.json",
                Path(output_dir) / "test_no_content_type.json",
            }

            for output_file in Path(output_dir).glob("*.json"):
                parser_output = ParserOutput.parse_file(output_file)
                assert isinstance(parser_output, ParserOutput)

                # Any html data should be parsed successfully as it is not using the
                # azure api, the pdf data should also be parsed successfully as we
                # should re-attempt download using the large document endpoint upon
                # HttpResponseError

                if parser_output.document_content_type == CONTENT_TYPE_HTML:
                    assert parser_output.html_data.text_blocks not in [[], None]

                if parser_output.document_content_type == CONTENT_TYPE_PDF:
                    assert parser_output.pdf_data.text_blocks not in [[], None]
                    assert parser_output.pdf_data.md5sum != ""
                    assert parser_output.pdf_data.page_metadata not in [[], None]
