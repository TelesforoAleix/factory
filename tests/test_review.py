

def test_review_skill_names_document_and_contract_rules():
    from cplane.skills import instructions

    text = instructions("slice-review")
    assert "docs/contracts.md" in text and "docs/claims.json" in text and "AGENTS.md document map" in text
    assert "contract_changes" in text and "`fix` finding" in text
    assert "contract_changes" in instructions("brief")
