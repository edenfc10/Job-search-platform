async def test_console_contains_human_input_checkpoint(client):
    page = await client.get("/")
    script = await client.get("/static/app.js")

    assert page.status_code == 200
    assert 'id="human-input-panel"' in page.text
    assert 'id="human-question-list"' in page.text
    assert 'id="save-human-btn"' in page.text
    assert script.status_code == 200
    assert "/human-input" in script.text
    assert "renderHumanInput(app)" in script.text
