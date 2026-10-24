
import re
import uuid

from invoice_parser import parse_invoice_batch
from agent import analyze_batch
from models import InvoiceProposal


ALLOWED_ACTIONS = {
    "settle_invoice",
    "request_approval",
    "hold_invoice",
    "reject_duplicate",
    "open_exception",
}

REFERENCE_PATTERN = re.compile(
    r"\[[^\[\]]+\]"
)


def package_to_text(package):
    """
    Convert package content into searchable text.
    Used to verify evidence references.
    """

    if isinstance(package, str):
        return package

    if isinstance(package, dict):
        return " ".join(
            package_to_text(value)
            for value in package.values()
        )

    if isinstance(package, list):
        return " ".join(
            package_to_text(value)
            for value in package
        )

    return str(package)


def validate_package_ids(packages):
    """
    Validate package IDs before AI analysis.
    """

    package_ids = []

    for package in packages:

        if not isinstance(package, dict):
            raise ValueError(
                "Invalid invoice package"
            )

        package_id = package.get(
            "packageId",
            package.get("package_id")
        )

        if not isinstance(package_id, str):
            raise ValueError(
                "Missing package ID"
            )

        package_id = package_id.strip()

        if not package_id:
            raise ValueError(
                "Empty package ID"
            )

        package_ids.append(package_id)

    if len(package_ids) != 12:
        raise ValueError(
            "Exactly 12 invoice packages required"
        )

    if len(set(package_ids)) != len(package_ids):
        raise ValueError(
            "Duplicate package IDs"
        )

    return package_ids


def validate_evidence(
    package,
    evidence_refs,
    rationale
):
    """
    Validate exactly three unique evidence references.

    Each reference must:
    - Be a bracketed reference.
    - Exist in the original invoice package.
    - Be cited in the rationale.
    """

    if not isinstance(evidence_refs, list):
        raise ValueError(
            "Invalid evidence references"
        )

    if len(evidence_refs) != 3:
        raise ValueError(
            "Exactly three evidence references required"
        )

    if not all(
        isinstance(ref, str)
        for ref in evidence_refs
    ):
        raise ValueError(
            "Evidence references must be strings"
        )

    if len(set(evidence_refs)) != 3:
        raise ValueError(
            "Evidence references must be unique"
        )

    package_text = package_to_text(package)

    for ref in evidence_refs:

        if not REFERENCE_PATTERN.fullmatch(ref):
            raise ValueError(
                f"Invalid evidence reference: {ref}"
            )

        if ref not in package_text:
            raise ValueError(
                f"Evidence reference not found in package: {ref}"
            )

        if ref not in rationale:
            raise ValueError(
                f"Rationale must cite evidence: {ref}"
            )


def generate_proposals(batch):
    """
    Validate the invoice batch, analyze it with AI,
    and generate one proposal per invoice package.

    Proposals are not executed here.
    """

    if not isinstance(batch, dict):
        raise ValueError(
            "Invalid invoice batch"
        )

    # Parse and validate the batch.
    parsed_batch = parse_invoice_batch(batch)

    packages = [
        item["originalPackage"]
        for item in parsed_batch["packages"]
    ]

    # Validate package IDs and exact package count.
    package_ids = validate_package_ids(
        packages
    )

    package_map = {}

    for package in packages:

        package_id = package.get(
            "packageId",
            package.get("package_id")
        )

        package_map[package_id] = package

    # Send validated packages to the AI.
    ai_batch = {
        "batchId": parsed_batch["batchId"],
        "policyRevision": parsed_batch.get(
            "policyRevision"
        ),
        "packages": packages,
    }

    ai_result = analyze_batch(
        ai_batch
    )

    if not isinstance(ai_result, dict):
        raise ValueError(
            "Invalid AI response"
        )

    raw_proposals = ai_result.get(
        "proposals"
    )

    if not isinstance(raw_proposals, list):
        raise ValueError(
            "Invalid AI proposals"
        )

    if len(raw_proposals) != len(packages):
        raise ValueError(
            "AI must return one proposal per package"
        )

    proposals = []
    seen_packages = set()

    for raw in raw_proposals:

        if not isinstance(raw, dict):
            raise ValueError(
                "Invalid proposal"
            )

        # Validate package ID.
        package_id = raw.get(
            "packageId"
        )

        if not isinstance(package_id, str):
            raise ValueError(
                "Invalid proposal package ID"
            )

        if package_id not in package_map:
            raise ValueError(
                f"AI returned unknown package: {package_id}"
            )

        if package_id in seen_packages:
            raise ValueError(
                f"Duplicate package proposal: {package_id}"
            )

        seen_packages.add(package_id)

        # Validate action.
        action = raw.get(
            "action"
        )

        if action not in ALLOWED_ACTIONS:
            raise ValueError(
                f"AI returned invalid action: {action}"
            )

        # Validate invoice facts.
        facts = raw.get(
            "facts"
        )

        if not isinstance(facts, dict):
            raise ValueError(
                "Invalid invoice facts"
            )

        # Validate rationale.
        rationale = raw.get(
            "rationale"
        )

        if not isinstance(rationale, str):
            raise ValueError(
                "Invalid rationale"
            )

        if not 60 <= len(rationale) <= 1500:
            raise ValueError(
                "Rationale must be 60 to 1500 characters"
            )

        # Validate evidence references.
        evidence_refs = raw.get(
            "evidenceRefs"
        )

        validate_evidence(
            package=package_map[package_id],
            evidence_refs=evidence_refs,
            rationale=rationale
        )

        # Generate a unique action ID.
        action_id = str(
            uuid.uuid4()
        )

        proposal = {
            "packageId": package_id,
            "actionId": action_id,
            "action": action,
            "facts": facts,
            "evidenceRefs": evidence_refs,
            "rationale": rationale,
        }

        # Validate the proposal using Pydantic.
        validated = InvoiceProposal.model_validate(
            proposal
        )

        proposals.append(
            validated.model_dump(
                by_alias=True
            )
        )

    # Confirm every package received exactly one proposal.
    if seen_packages != set(package_ids):
        raise ValueError(
            "Missing invoice package proposal"
        )

    # Return proposals in original package order.
    proposal_map = {
        proposal["packageId"]: proposal
        for proposal in proposals
    }

    ordered_proposals = [
        proposal_map[package_id]
        for package_id in package_ids
    ]

    return ordered_proposals
