
import json

from openai import OpenAI

from config import OPENAI_API_KEY, AI_MODEL


client = OpenAI(
    api_key=OPENAI_API_KEY
)


SYSTEM_PROMPT = """
You are an invoice decision assistant.

Your job is to analyze invoice packages and propose exactly one
business action for each package.

Allowed actions:

1. settle_invoice
2. request_approval
3. hold_invoice
4. reject_duplicate
5. open_exception

Rules:

- Read the complete package and its business policy.
- Use only evidence supplied in the package.
- Do not assume an invoice is approved merely because it is valid.
- Distinguish commercial validity from delegated payment authority.
- A duplicate means the same commercial invoice was already paid.
- A different invoice from the same vendor is not a duplicate.
- If required verification is pending, use hold_invoice.
- If material records conflict, use open_exception.
- If a valid invoice exceeds delegated authority, use request_approval.
- Use settle_invoice only when the invoice is valid, reconciled,
  and within autonomous authority.
- Do not confuse examples, archived records, training decoys,
  or irrelevant action words with decisive evidence.
- Do not invent facts, invoice numbers, amounts, or references.

Return JSON only.

Output structure:

{
  "proposals": [
    {
      "packageId": "...",
      "action": "...",
      "facts": {
        "vendorName": "...",
        "invoiceNumber": "...",
        "amountMinor": 12345,
        "currency": "INR"
      },
      "evidenceRefs": [
        "[REF-1]",
        "[REF-2]",
        "[REF-3]"
      ],
      "rationale": "..."
    }
  ]
}

Requirements:

- Exactly one proposal per package.
- Exactly three decisive evidence references per proposal.
- Evidence references must be copied exactly from the package.
- Do not include cover-sheet references or irrelevant examples.
- Rationale must be 60 to 1500 characters.
- Explain why the chosen action is correct.
- Mention at least two evidence references in the rationale.
"""


def analyze_batch(batch):

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured"
        )

    packages = batch.get("packages")

    if not isinstance(packages, list):
        raise ValueError("Invalid invoice packages")

    if not packages:
        raise ValueError("Empty invoice batch")

    user_prompt = {
        "batchId": batch.get("batchId"),
        "policyRevision": batch.get("policyRevision"),
        "packages": packages
    }

    response = client.chat.completions.create(
        model=AI_MODEL,
        temperature=0,
        response_format={
            "type": "json_object"
        },
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": json.dumps(
                    user_prompt,
                    ensure_ascii=False
                )
            }
        ]
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError(
            "AI returned an empty response"
        )

    result = json.loads(content)

    return result
