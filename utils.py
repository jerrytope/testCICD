import ast
import base64
import hashlib
import os
import re
import time
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

import nltk
import openai
import requests
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from custom_logger import setup_logger
from pydantic import BaseModel, ConfigDict, Field, create_model
from PyPDF2 import PdfReader
from settings import Settings

logger = setup_logger(__name__)

nltk.download("stopwords")
nltk.download("punkt_tab")

settings = Settings()

azure_client = openai.AzureOpenAI(
    api_version=settings.azure_api_version,
    api_key=settings.azure_api_key,
    azure_endpoint=settings.azure_api_base,
)


class Country(str, Enum):
    """Standardized country names for legal documents."""

    UK = "UK"
    UAE = "UAE"
    OTHER = "OTHER"


class Jurisdiction(str, Enum):
    """Standardized Jurisdiction names for legal documents"""

    DUBAI = "Dubai"
    ABU_DHABI = "Abu Dhabi"
    ADGM = "ADGM"
    AJMAN = "Ajman"
    FREE_ZONE = "Free Zone"
    DIFC = "DIFC"
    SHARJAH = "Sharjah"
    RAK = "Ras Al Khaimah"
    UMM_AL_QUWAIN = "Umm Al Quwain"
    FUJAIRAH = "Fujairah"
    UAE = "UAE"
    UNITED_KINGDOM = "UK"
    UNITED_STATES = "US"
    OTHER = "OTHER"


class LawLevel(str, Enum):
    CONSTITUTION = "Constitution"
    FEDERAL_LAWS = "Federal Laws"
    LOCAL_LAWS = "Local Laws"
    EXECUTIVE_REGULATIONS = "Executive Regulations"
    CABINET_RESOLUTIONS = "Cabinet Resolutions"
    FREE_ZONE_REGULATIONS = "Free Zone Regulations"
    INTERNATIONAL_TREATIES = "International Treaties"


class LegalDocument(BaseModel):
    model_config = ConfigDict(use_enum_values=True, validate_assignment=True)

    summary: str = Field(
        description="A concise summary of the document's content detailing the primary subject matter, primary legal domain, industries affected if any, target audience and applicability of the document, status of the document if it is a law or regulation, and any other relevant information."
    )

    title: str = Field(
        description="The title of the document describing what type of document it is and what it is about. The title should be concise and descriptive and must follow this format: [Document Type]: [Subject Matter] e.g. Law: The Constitution of the United States of America, Article: Explanation of the Constitution of the United States of America."
    )

    country: Country = Field(
        description="The country where the document originates from or is applicable to."
    )

    jurisdiction: Jurisdiction = Field(
        description="The most specific legal jurisdiction of the document. For the UAE, only set a jurisdiction if the document is specific to that specific jurisdiction."
    )

    is_law: bool = Field(
        description="Whether the document is a government issued law, regulation, treaty, etc. or not."
    )

    date_of_issue: str = Field(
        description="""The official date when the document was formally issued or published. For:
        - Legislation: date of enactment
        - Court decisions: date of judgment
        - Treaties: date of adoption
        - Academic articles: publication date
        Use the full date in YYYY-MM-DD format. If only year is known, use January 1st as default."""
    )

    effective_start_year: Optional[int] = Field(
        default=None,
        description="""The year when the document becomes legally effective or enforceable.""",
    )

    effective_end_year: Optional[int] = Field(
        default=None,
        description="""The year when the document ceases to be effective, if applicable. Use for:
        - Repealed or superseded legislation
        - Expired treaties or regulations
        - Time-limited provisions
        Leave empty if document is still in effect or has no specified end date.""",
    )

    law_level: Optional[LawLevel] = Field(
        description="""The hierarchy of law, from the Constitution to treaties, is structured as follows:
        Constitution:
        - The fundamental law that establishes the framework of governance and the rights of citizens.
        Federal Laws:
        - Laws enacted by the federal legislative body that apply across the nation.
        Local Laws:
        - Regulations and statutes specific to individual states or regions.
        Executive Regulations:
        - Detailed rules and procedures issued by the executive branch to implement and enforce laws.
        Cabinet Resolutions:
        - Decisions and directives issued by the Cabinet to address specific issues or provide guidance on law implementation.
        Free Zone Regulations:
        - Special laws and rules governing operations within designated free zones.
        International Treaties:
        - Agreements between nations that are binding under international law.
        Each level plays a distinct role in the legal framework:
        - The Constitution provides the supreme foundation of law.
        - Federal and local laws define obligations and rights within their respective jurisdictions.
        - Executive regulations and Cabinet resolutions ensure the practical application of laws.
        - Free zone regulations address specific economic or operational needs.
        - International treaties establish binding commitments between countries."""
    )


def get_years_from_dates(date_str):
    if date_str is None:
        return None

    try:
        # First try the standard format
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.year
    except ValueError:
        # If that fails, try to extract just the year
        if date_str and len(date_str) >= 4:
            try:
                year = int(date_str[:4])
                return year
            except ValueError:
                return None
        return None


def get_files_from_azure_container(container_name, connection_string):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        container_client = blob_service_client.get_container_client(
            container_name
        )
        blob_names = [blob.name for blob in container_client.list_blobs()]
        return blob_names
    except Exception as e:
        logger.error(
            f"An error occurred for container: {container_name}. Error: {e}"
        )
        return []


def download_blob_content(
    container_name, blob_name, connection_string, download_folder
):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        blob_path_parts = blob_name.split("/")
        blob_file_name = blob_path_parts[-1]
        blob_subdirectories = "/".join(blob_path_parts[:-1])
        full_download_path = os.path.join(download_folder, blob_subdirectories)
        os.makedirs(full_download_path, exist_ok=True)
        download_file_path = os.path.join(full_download_path, blob_file_name)
        with open(trim_filename(download_file_path), "wb") as download_file:
            download_file.write(blob_client.download_blob().readall())
        logger.debug(
            f"Successfully downloaded '{blob_name}' to '{download_file_path}'"
        )
        return trim_filename(download_file_path)
    except Exception as e:
        logger.error(f"Failed to download blob '{blob_name}'. Error: {e}")
        return None
    finally:
        blob_client.close()
        blob_service_client.close()


def download_txt_files_from_folder(
    container_name,
    folder_path,
    connection_string,
    download_folder,
    max_files=None,
):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        container_client = blob_service_client.get_container_client(
            container_name
        )

        # Ensure folder_path ends with / for proper prefix matching
        if folder_path and not folder_path.endswith("/"):
            folder_path += "/"

        downloaded_files = []

        # List all blobs in the specified folder
        blob_list = container_client.list_blobs(name_starts_with=folder_path)

        # Filter and download text files
        for blob in blob_list:
            if max_files and len(downloaded_files) >= max_files:
                break

            if blob.name.endswith(".txt"):
                blob_client = None
                try:
                    blob_client = blob_service_client.get_blob_client(
                        container=container_name, blob=blob.name
                    )

                    # Create the directory structure
                    blob_path_parts = blob.name.split("/")
                    blob_file_name = blob_path_parts[-1]
                    blob_subdirectories = "/".join(blob_path_parts[:-1])
                    full_download_path = os.path.join(
                        download_folder, blob_subdirectories
                    )
                    os.makedirs(full_download_path, exist_ok=True)

                    # Download the file
                    download_file_path = os.path.join(
                        full_download_path, blob_file_name
                    )
                    with open(
                        trim_filename(download_file_path), "wb"
                    ) as download_file:
                        download_file.write(
                            blob_client.download_blob().readall()
                        )

                    logger.debug(
                        f"Successfully downloaded '{blob.name}' to '{download_file_path}'"
                    )
                    downloaded_files.append(trim_filename(download_file_path))
                except Exception as e:
                    logger.error(
                        f"Failed to download blob '{blob.name}'. Error: {e}"
                    )
                finally:
                    if blob_client:
                        blob_client.close()

        return downloaded_files
    except Exception as e:
        logger.error(
            f"Failed to download txt files from folder '{folder_path}'. Error: {e}"
        )
        return []
    finally:
        container_client.close()
        blob_service_client.close()


def check_blob_exists(
    container_name, blob_name, connection_string, download_folder
):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        blob_path_parts = blob_name.split("/")
        blob_file_name = blob_path_parts[-1]
        blob_subdirectories = "/".join(blob_path_parts[:-1])
        full_download_path = os.path.join(download_folder, blob_subdirectories)
        os.makedirs(full_download_path, exist_ok=True)
        download_file_path = os.path.join(full_download_path, blob_file_name)
        if not blob_client.exists():
            logger.warning(f"Blob does not exist'{blob_name}'.")
            return None
        return trim_filename(download_file_path)
    except Exception as e:
        logger.error(f"Failed to download blob '{blob_name}'. Error: {e}")
        return None
    finally:
        blob_client.close()
        blob_service_client.close()


async def extract_template(content, types):
    if not types:
        logger.debug("Empty types list, returning none")
        return None
    if "not_contract" not in types:
        types.append("not_contract")
    if "other_contract" not in types:
        types.append("other_contract")
    TypeChoiceModel = create_model(
        "TypeChoiceModel",
        template=(Literal[tuple(types)], ...),
        __module__=__name__,
    )
    if len(content) > 100000:
        content = content[:100000]
    try:
        try:
            azure_client_async = openai.AsyncAzureOpenAI(
                api_version=settings.azure_api_version,
                api_key=settings.azure_api_key,
                azure_endpoint=settings.azure_api_base,
            )
            response = await azure_client_async.beta.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a helpful assistant. You will receive a contract or agreement and you have to return the type of that document.
                        Possible contract are: {", ".join(types)}.""",
                    },
                    {
                        "role": "user",
                        "content": f"What contract type is this document:: {content}",
                    },
                ],
                response_format=TypeChoiceModel,
                temperature=0,
            )
            if not response.choices or not response.choices[0].message.parsed:
                return None
            type_choice = response.choices[0].message.parsed
            logger.debug(f"extracted template: {type_choice}")
            return type_choice.template
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            return None
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None


def clean_entity_list(entity_list):
    if len(entity_list) == 0:
        return []
    # sort by start
    entity_list = sorted(entity_list, key=lambda x: x["start"])
    new_entity_list = [entity_list[0]]
    # remove embedded
    end = entity_list[0]["end"]
    for i in entity_list[1:]:
        if i["start"] <= end:
            continue
        else:
            end = i["end"]
            new_entity_list.append(i)
    return new_entity_list


def generate_pii_token(text, label, length=10):
    seed = f"{text.lower()}:{label.lower()}"
    sha256_hash = hashlib.sha256(seed.encode()).digest()
    base64_hash = base64.urlsafe_b64encode(sha256_hash).decode("utf-8")
    return f"[{label}_{base64_hash[:length]}]"


def replace_entities(text, entities, replacements=None):
    if replacements is None:
        replacements = {}
    offset = 0
    for entity in entities:
        start, end, original_text, label = (
            entity["start"] + offset,
            entity["end"] + offset,
            entity["text"],
            entity["label"],
        )
        replacement = None
        for rep_text, rep_replacement in replacements.items():
            if (
                original_text.lower() == rep_text.lower()
                and rep_replacement.startswith(f"[{label}")
            ):
                replacement = rep_replacement
                break
        if not replacement:
            replacement = generate_pii_token(original_text, label)
            replacements[original_text] = replacement
        text = text[:start] + replacement + text[end:]
        offset += len(replacement) - (end - start)
    return text, replacements


def find_string_positions(text, search_string):
    positions = []
    start = 0
    while start < len(text):
        start = text.find(search_string, start)
        if start == -1:
            break
        end = start + len(search_string)
        positions.append((start, end))
        start += len(search_string)  # Move past this occurrence
    return positions


def predict_entities_llm(text, labels):
    system_prompt = """You are a name entity recognition system.
        You will receive a list of labels to look for in a text.
        You will also receive the text to be analyzed.
        Do not introduce yourself or add any unnecessary information.
        Each extracted word should be tagged with one corresponding label.
        The return format is a JSON object with the following structure:
        {word : label}"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Text: {text}\nLabels: {labels}"},
    ]
    try:
        response = azure_client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=messages,
            temperature=0,
        )
        content = response.choices[0].message.content
        results = extract_dict_from_string(content)
        results_with_positions = []
        for item, label in results.items():
            positions = find_string_positions(text, item)
            for position in positions:
                results_with_positions.append(
                    {
                        "start": position[0],
                        "end": position[1],
                        "label": label,
                        "text": item,
                    }
                )
        return results_with_positions
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return {}


def anonymize_text_simple(text: str) -> str:
    # Define labels that require anonymization
    labels = [
        "Person",
        "Location",
        "Date",
        "Organisation",
        "Phone number",
        "Email adress",
    ]

    # Detect entities using LLM
    entities = predict_entities_llm(text, labels)
    entities = clean_entity_list(entities)

    # Replace detected entities with generated tokens
    anonymized_text, _ = replace_entities(text, entities)

    return anonymized_text


def standardize_date(date_str):
    # Define date formats to try
    date_formats = [
        "%Y-%m-%d",  # YYYY-MM-DD
        "%d/%m/%Y",  # DD/MM/YYYY
        "%m/%d/%Y",  # MM/DD/YYYY
        "%d %B %Y",  # 1 January 2024
        "%B %d, %Y",  # January 1, 2024
    ]
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Date format not recognized.")


def extract_date(text):
    # Define a regex pattern to match common date formats
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",  # Matches YYYY-MM-DD
        r"\b(\d{2}/\d{2}/\d{4})\b",  # Matches DD/MM/YYYY or MM/DD/YYYY
        r"\b(\d{1,2}(?:th|st|nd|rd)? [A-Za-z]+ \d{4})\b",  # Matches 1st January 2024
        r"\b([A-Za-z]+ \d{1,2}(?:th|st|nd|rd)?,? \d{4})\b",  # Matches January 1, 2024
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            date_str = match.group(1)
            try:
                # Try parsing the extracted date string to standardize the format
                return standardize_date(date_str)
            except ValueError:
                continue
    return None


def upload_file_to_storage(blob_client, file_path, content=None):
    try:
        if file_path is None:
            file_content = content
        else:
            with open(file_path, "rb") as file:
                file_content = file.read()
        blob_client.upload_blob(file_content, overwrite=True)
        logger.debug(f"File uploaded to Azure Storage: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload file to Azure Storage: {e}")
        return True


def setup_container(container_name: str, reset: bool = False):
    settings = Settings()
    # Azure Storage configuration
    azure_connection_string = settings.azure_connection_string
    azure_container_name = container_name
    blob_service_client = BlobServiceClient.from_connection_string(
        azure_connection_string
    )
    try:
        blob_service_client.create_container(azure_container_name)
        logger.debug(
            f"Azure Storage container created: {azure_container_name}"
        )
    except ResourceExistsError:
        if reset:
            blob_service_client.delete_container(azure_container_name)
            while True:
                try:
                    blob_service_client.create_container(azure_container_name)
                    break
                except Exception:
                    time.sleep(10)
                    continue
            logger.warning(f"container recreated: {azure_container_name}")
        else:
            logger.debug(f"container already exists: {azure_container_name}")

    container_client = blob_service_client.get_container_client(
        azure_container_name
    )
    return container_client


def url_to_filename(url):
    # Replace '://' with '_'
    filename = url.replace("://", "_")

    # Replace non-alphanumeric characters with underscores
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)

    return filename


def download_pdf(url, save_path):
    try:
        response = requests.get(url, verify=False)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(response.content)
            logger.debug(f"PDF downloaded successfully: {save_path}")
            try:
                _ = PdfReader(save_path)
            except Exception as e:
                logger.error(f"Error reading PDF, will not be save: {e}")
                os.remove(save_path)
        else:
            logger.error(
                f"Failed to download PDF: HTTP status code {response.status_code}"
            )
    except Exception as e:
        logger.error(f"An error occurred: {e}")


def trim_filename(download_file_path: str, max_length: int = 255) -> str:
    # Get the directory and filename
    directory, filename = os.path.split(download_file_path)
    # Get the file extension
    file_extension = os.path.splitext(filename)[1]
    # Determine the max length for the filename, considering the directory length
    max_filename_length = (
        max_length - len(directory) - 1 - len(file_extension)
    )  # Adjust for file extension

    # If the total path length is already within the limit, return it as is
    if len(download_file_path) <= max_length:
        return download_file_path

    # Trim the filename to fit the maximum length
    if len(filename) > max_filename_length:
        trimmed_filename = filename[
            :max_filename_length
        ]  # Trim the filename to fit
    else:
        trimmed_filename = filename

    # Reconstruct the full path with the trimmed filename
    new_file_path = os.path.join(directory, trimmed_filename + file_extension)

    # Ensure the new full path does not exceed max_length
    if len(new_file_path) > max_length:
        # Further trim if necessary (e.g., trim the directory name or filename further)
        raise ValueError(
            "The full path exceeds the maximum length after adjustment."
        )

    return new_file_path


def extract_dict_from_string(s):
    try:
        start = s.index("{")
        partial_dict_str = s[start:]
        # Extract key-value pairs using regex, allowing for incomplete pairs
        key_value_pattern = re.compile(
            r"([\'\"]?[\w\s]+[\'\"]?)\s*:\s*([\'\"].*?[\'\"]|\d+|\w+)?"
        )
        matches = key_value_pattern.findall(partial_dict_str)

        # Build the dictionary from extracted key-value pairs
        extracted_dict = {}
        for match in matches:
            key, value = match
            # Check if both key and value are valid
            if key:
                # Remove quotes from key if present
                key = key.strip("'\" ")
                if value:
                    # Convert value to appropriate type
                    try:
                        value = ast.literal_eval(value)
                    except (ValueError, SyntaxError):
                        pass
                else:
                    value = None
                extracted_dict[key] = value

        # Clean up the dictionary by removing any elements where either key or value is None
        cleaned_dict = {
            k: v
            for k, v in extracted_dict.items()
            if k is not None and v is not None
        }

        return cleaned_dict
    except ValueError as e:
        return f"Error: {e}"


def truncate_to_7kb(input_string):
    max_size = 7 * 1024  # 32 KB in bytes
    encoded_string = input_string.encode("utf-8")

    if len(encoded_string) <= max_size:
        return input_string  # No truncation needed
    output = ""
    size = 0

    for char in input_string:
        char_size = len(char.encode("utf-8"))
        if size + char_size > max_size:
            break
        output += char
        size += char_size

    return output


if __name__ == "__main__":
    from rich import print as rprint

    rprint(
        download_txt_files_from_folder(
            "documentattachments",
            "attachments/011b323c-9c79-4d87-ae93-900cd4abd1b5/AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0A3-fgqUbGEU_IxRImi7HangAAAwl-wgAAARIAEAAATFad3rzuSrtXd9IuKfpM/",
            settings.azure_connection_string,
            "../tmp",
            max_files=1,
        )
    )
