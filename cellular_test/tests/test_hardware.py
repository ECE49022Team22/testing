"""Real-hardware / real-network checks. Skipped unless RUN_HW=1."""

import os

import pytest

pytestmark = pytest.mark.hardware


@pytest.fixture(scope="module")
def link():
    from notecard_link import NotecardLink, open_card

    return NotecardLink(open_card())


def test_card_version(link):
    rsp = link.version()
    assert rsp.get("device", "").startswith("dev:")


def test_hub_status(link):
    assert "status" in link.hub_status()


def test_wireless_status(link):
    assert "err" not in link.wireless_status()


def test_notehub_token():
    import cloud_inject

    cfg = cloud_inject.env_config()
    token = cloud_inject.access_token(cfg)
    rsp = cloud_inject.requests.get(
        f"{cloud_inject.API}/v1/projects/{cfg['PROJECT_UID']}/devices/{cfg['DEVICE_UID']}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert rsp.status_code == 200, rsp.text
