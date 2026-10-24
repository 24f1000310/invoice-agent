
import json
import re
from typing import Any


REFERENCE_PATTERN = re.compile(r"\[[^\[\]]+\]")


def extract_references(text: str) -> list[str]:
    """
    Extract evidence references such as [REF-001]
    from a text string.
    """
    if not isinstance(text, str):
        return []

    references = REFERENCE_PATTERN.findall(text)

    # Preserve order and remove duplicates.
    return list(dict.fromkeys(references))


def value_to_text(value: Any) -> str:
    """
    Convert invoice data into readable text without
    discarding nested documents or evidence.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        return "\n".join(
            value_to_text(item)
            for item in value
        )

    if isinstance(value, dict):
        lines = []

        for key, item in value.items():
            item_text = value_to_text(item)

            if item_text:
                lines.append(
                    f"{key}: {item_text}"
                )

        return "\n".join(lines)

    return str(value)


def parse_invoice_package(package: dict) -> dict:
    """
    Parse one invoice package.

    Keeps the original package intact and adds:
      - packageId
      - packageText
      - evidenceRefs

    Does not make payment decisions.
    """

    if not isinstance(package, dict):
        raise ValueError(
            "Invoice package must be a JSON object"
        )

    package_id = package.get("packageId")

    if not isinstance(package_id, str):
        raise ValueError(
            "Invoice package is missing packageId"
        )

    package_id = package_id.strip()

    if not package_id:
        raise ValueError(
            "Invoice package has an empty packageId"
        )

    # Convert the entire package to text.
    # This preserves policy, invoice details,
    # documents, payment records, and other evidence.
    package_text = value_to_text(package)

    # Extract references from the complete package.
    evidence_refs = extract_references(
        package_text
    )

    return {
        "packageId": package_id,
        "packageText": package_text,
        "evidenceRefs": evidence_refs,
        "originalPackage": package
    }


def parse_invoice_batch(batch: dict) -> dict:
    """
    Parse the complete invoice batch.

    Returns the batch metadata and all parsed packages.
    """

    if not isinstance(batch, dict):
        raise ValueError(
            "Invoice batch must be a JSON object"
        )

    batch_id = batch.get("batchId")

    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError(
            "Invoice batch is missing batchId"
        )

    packages = batch.get("packages")

    if not isinstance(packages, list):
        raise ValueError(
            "Invoice batch packages must be a list"
        )

    if not packages:
        raise ValueError(
            "Invoice batch contains no packages"
        )

    parsed_packages = []
    seen_ids = set()

    for package in packages:

        parsed = parse_invoice_package(package)

        package_id = parsed["packageId"]

        if package_id in seen_ids:
            raise ValueError(
                f"Duplicate packageId: {package_id}"
            )

        seen_ids.add(package_id)

        parsed_packages.append(parsed)

    return {
        "batchId": batch_id,
        "policyRevision": batch.get(
            "policyRevision"
        ),
        "packages": parsed_packages
    }


def get_package_text(package: dict) -> str:
    """
    Return the complete text representation of
    a package for evidence validation or AI analysis.
    """

    parsed = parse_invoice_package(package)

    return parsed["packageText"]


def get_package_references(package: dict) -> list[str]:
    """
    Return all evidence references found in a package.
    """

    parsed = parse_invoice_package(package)

    return parsed["evidenceRefs"]
