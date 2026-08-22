#!/usr/bin/env python3
"""Certify the clinic workspace against a running Docassemble server.

The driver uses an ordinary browser for authentication and clinic actions. It
uses Docassemble's session API only to answer the long, already-certified child
interviews and to inspect synthetic test sessions. The API key must belong to
the isolated certification server; never point this driver at production.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
import json
import re
import secrets
import statistics
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select, WebDriverWait


ROOT = Path(__file__).resolve().parents[2]
CERTIFICATION = ROOT / "tests" / "certification"
sys.path.insert(0, str(CERTIFICATION))

from runtime_driver import (  # noqa: E402
    Client,
    build_answer,
    display_text,
    field_info,
    is_download_waiting_screen,
    is_error,
    question_id,
    question_variable,
    resolve_generic,
)


MATTER_INTERVIEW = (
    "docassemble.MATC1ADivorceJointPetition:"
    "data/questions/main_student_packet.yml"
)
DASHBOARD_INTERVIEW = (
    "docassemble.MATC1ADivorceJointPetition:"
    "data/questions/main_clinic_dashboard.yml"
)

DOCUMENT_TITLES = {
    "motion_to_amend": "Motion to convert a 1B divorce to a joint 1A divorce",
    "joint_petition": "Joint petition for divorce",
    "irretrievable_breakdown_affidavit": "Affidavit of irretrievable breakdown",
    "r408": "Report of Absolute Divorce or Annulment (R408)",
    "late_marriage_certificate_motion": "Motion to file marriage certificate late",
    "care_or_custody_affidavit": "Affidavit disclosing care or custody proceedings",
    "child_support_guidelines": "Child Support Guidelines Worksheet",
    "findings_and_determinations": "Findings and Determinations",
    "financial_statement_party_a": "Financial statement for Party A",
    "financial_statement_party_b": "Financial statement for Party B",
    "separation_agreement": "Separation agreement",
    "affidavit_of_indigency": "Affidavit of indigency",
    "temporary_orders_packet": "Temporary orders packet",
}

WORKFLOW_REPRESENTATIVES = (
    "motion_to_amend",
    "joint_petition",
    "r408",
    "late_marriage_certificate_motion",
    "care_or_custody_affidavit",
    "child_support_guidelines",
    "findings_and_determinations",
    "financial_statement_party_a",
    "separation_agreement",
    "affidavit_of_indigency",
    "temporary_orders_packet",
)


class CertificationFailure(RuntimeError):
    """Raised when the live runtime violates a certification assertion."""


def encoded_name(variable: str) -> str:
    return base64.urlsafe_b64encode(variable.encode()).decode().rstrip("=")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class SyntheticUser:
    user_id: int
    username: str
    password: str
    privilege: str


class AdminApi:
    def __init__(self, server: str, api_key: str, timeout: int = 30):
        self.server = server.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.http = requests.Session()

    def create_privilege(self, name: str) -> None:
        existing = self.http.get(
            f"{self.server}/api/privileges",
            params={"key": self.api_key},
            timeout=self.timeout,
        )
        existing.raise_for_status()
        if name in existing.json():
            return
        response = self.http.post(
            f"{self.server}/api/privileges",
            params={"key": self.api_key},
            data={"privilege": name},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def create_user(self, privilege: str, label: str) -> SyntheticUser:
        suffix = secrets.token_hex(6)
        # Docassemble's account API accepts the reserved .invalid suffix, but
        # its interactive sign-in validator rejects that address. example.com
        # is reserved for documentation and allows the browser login to prove
        # the same credentials that the API created.
        username = f"clinic-cert-{label}-{suffix}@example.com"
        password = "ClinicCert-" + secrets.token_urlsafe(18)
        response = self.http.post(
            f"{self.server}/api/user/new",
            params={"key": self.api_key},
            json={
                "username": username,
                "password": password,
                "first_name": "Clinic",
                "last_name": f"Certification {label.title()}",
                "privileges": [privilege],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return SyntheticUser(
            user_id=int(response.json()["user_id"]),
            username=username,
            password=password,
            privilege=privilege,
        )

    def variables(self, session: str) -> dict[str, Any]:
        response = self.http.get(
            f"{self.server}/api/session",
            params={
                "key": self.api_key,
                "i": MATTER_INTERVIEW,
                "session": session,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("variables", payload)


class ClinicBrowser:
    def __init__(self, server: str, artifacts: Path, timeout: int = 30):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,1200")
        options.add_argument("--hide-scrollbars")
        self.driver = webdriver.Chrome(options=options)
        self.server = server.rstrip("/")
        self.artifacts = artifacts
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.wait = WebDriverWait(self.driver, timeout)

    def close(self) -> None:
        self.driver.quit()

    def body_text(self) -> str:
        return self.driver.find_element(By.TAG_NAME, "body").text

    def wait_for_text(self, text: str) -> None:
        try:
            self.wait.until(lambda driver: text in driver.find_element(By.TAG_NAME, "body").text)
        except TimeoutException as exc:
            raise CertificationFailure(
                f"Timed out waiting for {text!r}; page contains {self.body_text()[:1000]!r}"
            ) from exc

    def screenshot(self, name: str) -> str:
        path = self.artifacts / f"{name}.png"
        self.driver.save_screenshot(str(path))
        path.with_suffix(".html").write_text(self.driver.page_source)
        return str(path)

    def login(self, user: SyntheticUser) -> None:
        self.driver.get(f"{self.server}/user/sign-in")
        email = self.wait.until(lambda driver: driver.find_element(By.ID, "email"))
        email.send_keys(user.username)
        self.driver.find_element(By.ID, "password").send_keys(user.password)
        submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
        self.driver.execute_script("arguments[0].click();", submit)
        try:
            self.wait.until(lambda driver: "/user/sign-in" not in driver.current_url)
        except TimeoutException as exc:
            raise CertificationFailure(
                "Synthetic clinic account did not pass interactive sign-in: "
                + self.body_text()[:500]
            ) from exc

    def open_interview(
        self,
        interview: str,
        *,
        new_session: bool = False,
        session: str | None = None,
        url_args: dict[str, Any] | None = None,
    ) -> None:
        query_items: list[tuple[str, Any]] = [("i", interview)]
        if new_session:
            query_items.extend((("new_session", 1), ("from_list", 1)))
        if session:
            query_items.append(("session", session))
        query_items.extend((url_args or {}).items())
        self.driver.get(f"{self.server}/interview?{urlencode(query_items)}")

    def _visible_submit(self):
        candidates = self.driver.find_elements(
            By.CSS_SELECTOR,
            "button[type='submit'], input[type='submit']",
        )
        visible = [item for item in candidates if item.is_displayed() and item.is_enabled()]
        if not visible:
            self.screenshot("clinic-runtime-no-submit")
            raise CertificationFailure(
                "The current screen has no visible submit control: "
                + self.body_text()[:1200]
            )
        preferred = [
            item
            for item in visible
            if any(
                word in ((item.text or item.get_attribute("value") or "").lower())
                for word in ("continue", "next", "create", "save")
            )
        ]
        return (preferred or visible)[-1]

    def submit(self) -> None:
        self.driver.execute_script("arguments[0].click();", self._visible_submit())

    def set_text(self, variable: str, value: str) -> None:
        element = self.driver.find_element(By.NAME, encoded_name(variable))
        element.clear()
        element.send_keys(value)

    def wait_for_variable(self, variable: str) -> None:
        encoded = encoded_name(variable)
        try:
            self.wait.until(
                lambda driver: bool(driver.find_elements(By.NAME, encoded))
            )
        except TimeoutException as exc:
            self.screenshot("clinic-runtime-missing-answer-field")
            raise CertificationFailure(
                f"Timed out waiting for answer field {variable!r}; "
                f"page contains {self.body_text()[:1000]!r}"
            ) from exc

    def select_value(self, variable: str, value: str) -> None:
        selector = f"input[name='{encoded_name(variable)}'][value='{value}']"
        element = self.driver.find_element(By.CSS_SELECTOR, selector)
        self.driver.execute_script("arguments[0].click();", element)

    def create_matter(self, label: str, document_ids: tuple[str, ...]) -> str:
        self.open_interview(DASHBOARD_INTERVIEW)
        self.wait_for_text("Clinic divorce matters")
        self.click_action("Create matter")
        self.wait_for_text("Create a clinic divorce matter")
        self.set_text("clinic_safe_label", label)
        self.select_value("clinic_case_posture", "existing_1b_conversion")
        self.select_value("clinic_party_a_relationship", "represented_client")
        self.select_value("clinic_party_b_relationship", "other_party")
        self.submit()
        self.wait_for_text("What documents should this matter prepare?")
        for document_id in document_ids:
            label_text = DOCUMENT_TITLES[document_id]
            checkbox = self.driver.find_element(
                By.CSS_SELECTOR,
                f"input[aria-label={json.dumps(label_text)}]",
            )
            if not checkbox.is_selected():
                self.driver.execute_script("arguments[0].click();", checkbox)
        self.submit()
        self.wait_for_text(label)
        session_match = re.search(r"Session:\s*([A-Za-z0-9_-]+)", self.body_text())
        if session_match:
            return session_match.group(1)

        # Ordinary clinic accounts do not necessarily receive Docassemble's
        # debug footer. Prove dashboard persistence and recover the opaque
        # session key from the matter's rendered Open matter link instead.
        self.click_action("Caseload dashboard")
        self.wait_for_text(label)
        for card in self.driver.find_elements(By.CSS_SELECTOR, ".clinic-matter-card"):
            if label not in card.text:
                continue
            for link in card.find_elements(By.TAG_NAME, "a"):
                link_label = link.text or link.get_attribute("textContent") or ""
                if "Open matter" not in link_label:
                    continue
                session_values = parse_qs(
                    urlparse(link.get_attribute("href") or "").query
                ).get("session", [])
                if session_values:
                    session = session_values[0]
                    self.open_interview(MATTER_INTERVIEW, session=session)
                    self.wait_for_text(label)
                    return session

        self.screenshot("clinic-create-matter-missing-session")
        raise CertificationFailure(
            "Could not recover the new matter session from its dashboard card; "
            f"page contains {self.body_text()[:1200]!r}"
        )

    def assert_healthy_page(self, route_name: str) -> None:
        danger = [
            item.text
            for item in self.driver.find_elements(
                By.CSS_SELECTOR,
                ".daerror, .dainterviewerror, .alert-danger",
            )
            if item.is_displayed()
        ]
        if danger:
            self.screenshot("clinic-route-error-" + re.sub(r"[^a-z0-9]+", "-", route_name.lower()))
            raise CertificationFailure(
                f"Route {route_name!r} displayed an error: {danger[:3]!r}"
            )

    def return_to_matter(self, label: str) -> None:
        self.click_action("Return to matter")
        self.wait_for_text(label)
        self.assert_healthy_page("Return to matter")

    def action_url_for_document(self, document_title: str, action_text: str) -> str:
        for _ in range(5):
            try:
                for card in self.driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card"):
                    if document_title not in card.text:
                        continue
                    for link in card.find_elements(By.TAG_NAME, "a"):
                        link_label = link.text or link.get_attribute("textContent") or ""
                        if action_text in link_label:
                            return link.get_attribute("href")
            except StaleElementReferenceException:
                time.sleep(0.2)
                continue
        raise CertificationFailure(
            f"Could not find {action_text!r} for {document_title!r}"
        )

    def click_action_for_document(self, document_title: str, action_text: str) -> None:
        """Click a rendered document action, including JavaScript ask links."""

        for _ in range(5):
            try:
                for card in self.driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card"):
                    if document_title not in card.text:
                        continue
                    for link in card.find_elements(By.TAG_NAME, "a"):
                        link_label = link.text or link.get_attribute("textContent") or ""
                        if action_text in link_label:
                            self.driver.execute_script(
                                "arguments[0].style.position = 'fixed';"
                                "arguments[0].style.top = '240px';"
                                "arguments[0].style.left = '240px';"
                                "arguments[0].style.zIndex = '2147483647';",
                                link,
                            )
                            link.click()
                            return
            except StaleElementReferenceException:
                time.sleep(0.2)
                continue
        raise CertificationFailure(
            f"Could not click {action_text!r} for {document_title!r}"
        )

    def action_url(self, action_text: str) -> str:
        for link in self.driver.find_elements(By.TAG_NAME, "a"):
            if action_text in link.text:
                return link.get_attribute("href")
        raise CertificationFailure(f"Could not find workspace action {action_text!r}")

    def click_action(self, action_text: str) -> None:
        """Click a visible link or code button, including Docassemble ask actions."""

        for _ in range(5):
            try:
                controls = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "a, button, input[type='submit']",
                )
                for control in controls:
                    control_label = (
                        control.text
                        or control.get_attribute("textContent")
                        or control.get_attribute("value")
                        or ""
                    )
                    if action_text in control_label and control.is_displayed():
                        self.driver.execute_script("arguments[0].click();", control)
                        return
            except StaleElementReferenceException:
                time.sleep(0.2)
                continue
        raise CertificationFailure(f"Could not click workspace action {action_text!r}")


def load_comprehensive_scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge compatible generated scenarios for all clinic document families."""

    paths = (
        "026_both_long_financial_statements_at_upper_boundary.json",
        "034_fee_waiver_detailed_supplement.json",
        "021_five_children_built_worksheet_built_agreement.json",
    )
    variables: dict[str, Any] = {}
    cardinalities: dict[str, Any] = {}
    for filename in paths:
        scenario = json.loads(
            (CERTIFICATION / "generated_scenarios" / filename).read_text()
        )
        variables.update(scenario.get("variables", {}))
        cardinalities.update(scenario.get("expected_cardinalities", {}))
    variables["has_existing_1b_action"] = True
    variables["plaintiff_is_party_a"] = True
    return variables, cardinalities


def decoded_name(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
    except Exception:
        return value


def comparable(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value).strip().lower()


def desired_value(
    variable: str,
    variables: dict[str, Any],
    sequence_positions: dict[str, int],
) -> tuple[bool, Any]:
    if variable in variables:
        key = variable
    else:
        normalized = re.sub(r"\[\d+\]", "[i]", variable)
        if normalized not in variables:
            if variable.endswith(".there_is_another"):
                return True, False
            return False, None
        key = normalized
    value = variables[key]
    if isinstance(value, dict) and "$sequence" in value:
        sequence = list(value.get("$sequence") or [])
        position = sequence_positions.get(key, 0)
        if position < len(sequence):
            selected = sequence[position]
            sequence_positions[key] = position + 1
            return True, selected
        return True, value.get("$default", sequence[-1] if sequence else False)
    return True, value


def fallback_text(variable: str, input_type: str) -> str:
    lowered = variable.lower()
    if input_type == "email" or "email" in lowered:
        return "clinic.certification@example.com"
    if input_type == "tel" or "phone" in lowered:
        return "6175550100"
    if input_type == "date" or "date" in lowered:
        return "2020-01-15"
    if input_type == "number" or any(
        token in lowered
        for token in ("amount", "income", "expense", "value", "number", "count")
    ):
        return "100"
    if "zip" in lowered:
        return "02108"
    if lowered.endswith(".state") or lowered.endswith("_state"):
        return "MA"
    if "ssn" in lowered or "social_security" in lowered:
        return "6789"
    return "Test"


def choose_checkbox_values(desired: Any, available: list[str]) -> set[str]:
    if isinstance(desired, dict):
        return {
            comparable(key)
            for key, selected in desired.items()
            if selected and not str(key).startswith("$")
        }
    if isinstance(desired, (list, tuple, set)):
        return {comparable(item) for item in desired}
    if isinstance(desired, bool):
        return {comparable(item) for item in available} if desired else set()
    if desired not in (None, ""):
        return {comparable(desired)}
    return set()


def fill_rendered_form(
    browser: ClinicBrowser,
    variables: dict[str, Any],
    sequence_positions: dict[str, int],
) -> dict[str, Any]:
    """Fill the visible Docassemble form using the comprehensive path model."""

    driver = browser.driver
    controls = driver.find_elements(
        By.CSS_SELECTOR,
        "#daform input, #daform select, #daform textarea",
    )
    visible = [
        item
        for item in controls
        if item.is_enabled()
        and (
            item.is_displayed()
            or item.tag_name.lower() == "select"
            or (item.get_attribute("type") or "").lower()
            in {"radio", "checkbox", "file"}
        )
    ]
    for item in driver.find_elements(
        By.CSS_SELECTOR,
        "#daform .combobox-container input[type='hidden'][name]",
    ):
        if item.is_enabled() and item not in visible:
            visible.append(item)
    varname_aliases: dict[str, str] = {}
    for item in driver.find_elements(By.CSS_SELECTOR, "#daform input[name='_varnames']"):
        try:
            raw_aliases = item.get_attribute("value") or ""
            decoded_aliases = base64.urlsafe_b64decode(
                raw_aliases + "=" * (-len(raw_aliases) % 4)
            ).decode()
            encoded_aliases = json.loads(decoded_aliases)
            varname_aliases.update(
                {
                    encoded_placeholder: decoded_name(encoded_variable)
                    for encoded_placeholder, encoded_variable in encoded_aliases.items()
                }
            )
        except (TypeError, ValueError):
            continue
    by_name: dict[str, list[Any]] = {}
    for element in visible:
        name = element.get_attribute("name") or ""
        if not name or name.startswith("_"):
            continue
        by_name.setdefault(name, []).append(element)

    filled: dict[str, Any] = {}
    for group in driver.find_elements(
        By.CSS_SELECTOR, "#daform .da-field-group.da-field-checkboxes[data-varname]"
    ):
        variable = decoded_name(group.get_attribute("data-varname") or "")
        found, desired = desired_value(variable, variables, sequence_positions)
        options = group.find_elements(By.CSS_SELECTOR, "input[type='checkbox'].danon-nota-checkbox")
        available = [
            decoded_name(option.get_attribute("data-cbvalue") or "")
            for option in options
        ]
        selected = choose_checkbox_values(desired, available) if found else set()
        for option, option_value in zip(options, available):
            should_select = comparable(option_value) in selected
            if option.is_selected() != should_select:
                driver.execute_script("arguments[0].click();", option)
        none_options = group.find_elements(
            By.CSS_SELECTOR, "input[type='checkbox'].danota-checkbox"
        )
        if not selected and none_options and not none_options[0].is_selected():
            driver.execute_script("arguments[0].click();", none_options[0])
        elif (
            not selected
            and options
            and group.find_elements(
                By.XPATH,
                "./ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' darequired ')][1]",
            )
        ):
            driver.execute_script("arguments[0].click();", options[0])
            selected = {available[0]}
        filled[variable] = sorted(selected)

    upload_fixture = ROOT / "docassemble" / "MATC1ADivorceJointPetition" / "data" / "templates" / "r408.pdf"
    for encoded, elements in by_name.items():
        variable = varname_aliases.get(encoded, decoded_name(encoded))
        found, desired = desired_value(variable, variables, sequence_positions)
        tag = elements[0].tag_name.lower()
        input_type = (elements[0].get_attribute("type") or "").lower()
        if input_type == "hidden":
            try:
                native_select = driver.find_element(By.ID, encoded + "combobox")
            except Exception:
                continue
            if native_select.tag_name.lower() != "select":
                value = desired if found else fallback_text(variable, "text")
                if isinstance(value, (dict, list, tuple, set)):
                    value = fallback_text(variable, "text")
                value = str(value)
                driver.execute_script(
                    "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                    elements[0],
                    value,
                )
                for control_id in (encoded, encoded + "combobox"):
                    try:
                        control = driver.find_element(By.ID, control_id)
                        driver.execute_script(
                            "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                            control,
                            value,
                        )
                    except Exception:
                        pass
                filled[variable] = value
                continue
            options = native_select.find_elements(By.TAG_NAME, "option")
            wanted = comparable(desired) if found else ""
            option = next(
                (
                    item
                    for item in options
                    if comparable(item.get_attribute("value")) == wanted
                    and item.is_enabled()
                ),
                next(
                    (
                        item
                        for item in options
                        if item.is_enabled() and (item.get_attribute("value") or "")
                    ),
                    None,
                ),
            )
            if option is not None:
                selected_value = option.get_attribute("value")
                selected_text = option.text
                driver.execute_script(
                    "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                    elements[0],
                    selected_value,
                )
                try:
                    visible_combo = driver.find_element(By.ID, encoded)
                    visible_combo.click()
                    visible_combo.send_keys(Keys.CONTROL, "a")
                    visible_combo.send_keys(selected_text)
                    visible_combo.send_keys(Keys.ARROW_DOWN)
                    visible_combo.send_keys(Keys.ENTER)
                except Exception:
                    pass
                filled[variable] = selected_value
            continue
        if input_type in {"submit", "button", "reset"}:
            continue
        if input_type == "radio":
            available = [element.get_attribute("value") or "" for element in elements]
            wanted = comparable(desired) if found else ""
            choice = next(
                (element for element in elements if comparable(element.get_attribute("value")) == wanted),
                elements[0],
            )
            if not choice.is_selected():
                driver.execute_script("arguments[0].click();", choice)
            filled[variable] = choice.get_attribute("value")
            continue
        if input_type == "checkbox":
            # Docassemble checkbox groups encode each option in a distinct
            # input name. They are handled as a group above.
            continue
        if input_type == "file":
            # An optional upload with an explicitly empty modeled value must be
            # submitted empty. Uploading a fixture on that path can race
            # Docassemble's asynchronous uploader and repeat the same screen.
            if found and desired in (None, "", False):
                filled[variable] = None
                continue
            selected_fixture = upload_fixture
            if isinstance(desired, dict) and desired.get("$file"):
                selected_fixture = (ROOT / desired["$file"]).resolve()
            elements[0].send_keys(str(selected_fixture))
            filled[variable] = selected_fixture.name
            continue
        if tag == "select":
            options = elements[0].find_elements(By.TAG_NAME, "option")
            wanted = comparable(desired) if found else ""
            option = next(
                (
                    item
                    for item in options
                    if comparable(item.get_attribute("value")) == wanted
                    and item.is_enabled()
                ),
                next(
                    (
                        item
                        for item in options
                        if item.is_enabled() and (item.get_attribute("value") or "")
                    ),
                    None,
                ),
            )
            if option is not None:
                selected_value = option.get_attribute("value")
                Select(elements[0]).select_by_value(selected_value)
                filled[variable] = selected_value
            continue
        numeric_control = (
            elements[0].get_attribute("inputmode") in {"numeric", "decimal"}
            or bool(
                {"danumeric", "dacurrency"}.intersection(
                    (elements[0].get_attribute("class") or "").split()
                )
            )
        )
        value = desired if found else (
            (
                elements[0].get_attribute("value")
                or elements[0].get_attribute("min")
                or "0"
            )
            if numeric_control
            else fallback_text(variable, input_type)
        )
        if isinstance(value, (dict, list, tuple, set)):
            value = fallback_text(variable, input_type)
        value = str(value)
        element = elements[0]
        maxlength = element.get_attribute("maxlength")
        if maxlength and maxlength.isdigit():
            value = value[: int(maxlength)]
        if input_type == "date":
            driver.execute_script(
                "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                element,
                value,
            )
            filled[variable] = value
            continue
        try:
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(value)
        except Exception:
            driver.execute_script(
                "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                element,
                value,
            )
        filled[variable] = value
    for element in driver.find_elements(By.CSS_SELECTOR, "#daform select[required]"):
        if element.is_enabled() and not (element.get_attribute("value") or ""):
            driver.execute_script(
                "const s=arguments[0]; const o=[...s.options].find(x => !x.disabled && x.value); if(o){s.value=o.value; o.selected=true; s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('change',{bubbles:true}));}",
                element,
            )
    return filled


def submit_rendered_form(
    browser: ClinicBrowser,
    variables: dict[str, Any],
    sequence_positions: dict[str, int],
) -> None:
    """Choose a modeled code button, or use the ordinary continue control."""

    candidates = [
        item
        for item in browser.driver.find_elements(
            By.CSS_SELECTOR,
            "#daform button[type='submit'], #daform input[type='submit']",
        )
        if item.is_displayed() and item.is_enabled()
    ]
    if not candidates:
        browser.submit()
        return
    ordinary = [
        item
        for item in candidates
        if any(
            word in ((item.text or item.get_attribute("value") or "").lower())
            for word in ("continue", "next", "create", "save")
        )
    ]
    if ordinary:
        browser.driver.execute_script("arguments[0].click();", ordinary[-1])
        return
    sought_elements = browser.driver.find_elements(By.ID, "sought_variable")
    variable = (
        decoded_name(sought_elements[0].get_attribute("data-variable") or "")
        if sought_elements
        else ""
    )
    found, desired = desired_value(variable, variables, sequence_positions)
    if found and isinstance(desired, bool):
        wanted_words = {"yes", "true"} if desired else {"no", "false"}
        choice = next(
            (
                item
                for item in candidates
                if any(
                    word in (item.text or item.get_attribute("value") or "").strip().lower()
                    for word in wanted_words
                )
            ),
            candidates[0] if desired else candidates[-1],
        )
    else:
        choice = candidates[0]
    browser.driver.execute_script("arguments[0].click();", choice)


def rendered_page_token(browser: ClinicBrowser) -> tuple[str, str, tuple[str, ...]]:
    """Identify a rendered question even when adjacent screens share all text."""

    for _ in range(5):
        try:
            return (
                browser.driver.current_url,
                browser.driver.execute_script("return document.body.innerText"),
                tuple(
                    element.get_attribute("value") or ""
                    for element in browser.driver.find_elements(
                        By.CSS_SELECTOR,
                        "#daform input[name='_tracker'], #daform input[name='_question_name']",
                    )
                ),
            )
        except StaleElementReferenceException:
            time.sleep(0.05)
    # Repeated staleness means Docassemble is actively replacing the form, so
    # treat it as a changed page and let the caller refetch the settled DOM.
    return (
        browser.driver.current_url,
        "<redrawing>",
        (str(time.monotonic_ns()),),
    )


def drive_rendered_workflow(
    browser: ClinicBrowser,
    label: str,
    action_url: str | None,
    variables: dict[str, Any],
    *,
    max_steps: int = 500,
) -> dict[str, Any]:
    """Traverse a clinic child workflow entirely through rendered forms."""

    if action_url is not None:
        browser.driver.get(action_url)
    started = time.monotonic()
    screens: list[str] = []
    repeated: dict[str, int] = {}
    sequence_positions: dict[str, int] = {}
    for step in range(1, max_steps + 1):
        body = browser.body_text()
        if label in body and browser.driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card"):
            return {
                "steps": step - 1,
                "seconds": round(time.monotonic() - started, 3),
                "screens": screens,
            }
        lowered = body.lower()
        if any(
            marker in lowered
            for marker in (
                "there was an error",
                "an error occurred",
                "internal server error",
                "interview has an error",
                "something went wrong",
                "undefined variable",
                "traceback",
            )
        ):
            browser.screenshot("clinic-runtime-error")
            raise CertificationFailure(f"Rendered runtime error: {body[:1600]}")
        try:
            heading = " | ".join(
                item.text.strip()
                for item in browser.driver.find_elements(By.CSS_SELECTOR, "h1, .daquestion")
                if item.is_displayed() and item.text.strip()
            ) or body[:160]
        except StaleElementReferenceException:
            continue
        screens.append(heading[:300])
        try:
            state = canonical(
                {
                    "heading": heading,
                    "url": browser.driver.current_url,
                    "question": rendered_page_token(browser)[2],
                }
            )
        except StaleElementReferenceException:
            continue
        repeated[state] = repeated.get(state, 0) + 1
        if repeated[state] > 4:
            browser.screenshot("clinic-runtime-loop")
            raise CertificationFailure(f"Rendered workflow repeated one state: {heading[:500]}")
        signature_canvases = browser.driver.find_elements(By.ID, "dasigcanvas")
        if signature_canvases:
            canvas = signature_canvases[0]
            ActionChains(browser.driver).move_to_element_with_offset(
                canvas, 80, 80
            ).click_and_hold().move_by_offset(80, 25).move_by_offset(
                70, -35
            ).move_by_offset(90, 30).release().perform()
            save_buttons = [
                item
                for item in browser.driver.find_elements(By.CSS_SELECTOR, ".dasigsave")
                if item.is_displayed() and item.is_enabled()
            ]
            if not save_buttons:
                raise CertificationFailure("Signature screen did not expose its save action")
            before = rendered_page_token(browser)
            browser.driver.execute_script("arguments[0].click();", save_buttons[-1])
            browser.wait.until(
                lambda driver: rendered_page_token(browser) != before
            )
            continue
        try:
            fill_rendered_form(browser, variables, sequence_positions)
        except StaleElementReferenceException:
            # A choice can redraw dependent controls while this pass still has
            # references to the prior DOM. Refetch the current form next pass.
            continue
        before = rendered_page_token(browser)
        submit_rendered_form(browser, variables, sequence_positions)
        try:
            browser.wait.until(
                lambda driver: rendered_page_token(browser) != before
            )
        except TimeoutException as exc:
            browser.screenshot("clinic-runtime-stalled")
            raise CertificationFailure(
                f"Rendered workflow did not advance from: {heading[:500]}"
            ) from exc
    browser.screenshot("clinic-runtime-max-steps")
    raise CertificationFailure(
        f"Rendered workflow exceeded {max_steps} steps; last screen was {screens[-1] if screens else '<none>'}"
    )


def drive_forced_workflow(
    api: Client,
    admin: AdminApi,
    browser: ClinicBrowser,
    session: str,
    action_url: str,
    variables: dict[str, Any],
    cardinalities: dict[str, Any],
    *,
    max_steps: int = 500,
) -> dict[str, Any]:
    """Open a clinic action in the browser and answer its forced child stack."""

    browser.driver.get(action_url)
    question = api.question(MATTER_INTERVIEW, session, "")
    sequence_positions: dict[str, int] = {}
    seen: list[str] = []
    started = time.monotonic()
    for step in range(1, max_steps + 1):
        qid = question_id(question)
        seen.append(qid)
        if is_error(question):
            raise CertificationFailure(
                f"Runtime error on {qid!r}: {display_text(question)[:1200]}"
            )
        if (
            qid.replace("_", " ").lower() == "clinic workspace home"
            or "clinic_workspace_home" in (question.get("event_list") or [])
        ):
            return {
                "steps": step,
                "seconds": round(time.monotonic() - started, 3),
                "screens": seen,
            }
        if is_download_waiting_screen(question):
            time.sleep(2)
            question = api.question(MATTER_INTERVIEW, session, "")
            continue

        fields = field_info(question)
        needs_snapshot = any(
            field["datatype"]
            in {"object", "object_radio", "object_checkboxes", "object_multiselect"}
            for field in fields
        )
        current_variables = None
        if needs_snapshot:
            names = sorted(
                {
                    str(choice.get("value"))
                    for field in fields
                    for choice in field["choices"]
                    if isinstance(choice, dict) and choice.get("value") is not None
                }
            )
            current_variables = api.snapshot(
                MATTER_INTERVIEW,
                session,
                "",
                values=names,
            )
        answer = build_answer(
            question,
            variables,
            sequence_positions,
            cardinalities,
            current_variables,
        )
        question = answer_and_evaluate(
            api,
            session,
            answer,
            question.get("event_list") or [],
            question.get("questionName") if question.get("mandatory") else None,
        )
    raise CertificationFailure(
        f"Workflow exceeded {max_steps} steps; last screen was {question_id(question)!r}"
    )


def answer_and_evaluate(
    api: Client,
    session: str,
    variables: dict[str, Any],
    event_list: list[str],
    question_name: str | None,
) -> dict[str, Any]:
    """Save an answer and obtain the next forced-stack question atomically.

    A separate GET after saving can lose a browser-created ``force_ask`` stack.
    Docassemble's ``question=1`` request evaluates within the same transaction
    and is therefore required for clinic child-workflow certification.
    """

    payload = api._params(MATTER_INTERVIEW, session, "")
    uploads = {
        name: value["$file"]
        for name, value in variables.items()
        if isinstance(value, dict) and "$file" in value
    }
    ordinary = {name: value for name, value in variables.items() if name not in uploads}
    payload["variables"] = canonical(ordinary)
    payload["question"] = 1
    if event_list:
        payload["event_list"] = canonical(event_list)
    if question_name:
        payload["question_name"] = question_name
    with ExitStack() as stack:
        files = {
            name: stack.enter_context(open((ROOT / relative).resolve(), "rb"))
            for name, relative in uploads.items()
        }
        response = api.http.post(
            f"{api.server}/api/session",
            data=payload,
            files=files or None,
            timeout=api.timeout,
        )
    if response.status_code >= 400:
        raise CertificationFailure(
            f"Docassemble rejected the answer on {question_name or event_list}: "
            f"HTTP {response.status_code}: {response.text[:1200]}"
        )
    return response.json()


def certify_collaboration_lifecycle(
    args: argparse.Namespace,
    admin: AdminApi,
    owner_browser: ClinicBrowser,
    session: str,
    label: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    """Certify role boundaries and the working-file lifecycle in real pages."""

    collaborator = admin.create_user("clinic_student", "collaborator")
    supervisor = admin.create_user("clinic_supervisor", "supervisor")
    unrelated = admin.create_user("clinic_student", "unrelated")
    clinic_admin = admin.create_user("clinic_admin", "administrator")

    def owner_action(action_text: str, answers: dict[str, Any]) -> dict[str, Any]:
        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        return drive_rendered_workflow(
            owner_browser,
            label,
            owner_browser.action_url(action_text),
            answers,
            max_steps=args.max_steps,
        )

    for member, role in ((collaborator, "collaborator"), (supervisor, "supervisor")):
        owner_action(
            "Manage team",
            {
                "clinic_team_user_id": member.user_id,
                "clinic_team_role": role,
            },
        )

    owner_action(
        "Assign",
        {"clinic_document_assignee": collaborator.user_id},
    )
    session_variables = admin.variables(session)
    matter = session_variables["clinic_matter"]
    if matter["documents"]["motion_to_amend"]["assigned_user_id"] != collaborator.user_id:
        diagnostic_names = (
            "clinic_pending_action",
            "clinic_record_team_member",
            "clinic_record_document_assignment",
            "clinic_team_user_id",
            "clinic_team_role",
            "clinic_document_assignee",
        )
        raise CertificationFailure(
            "Rendered assignment did not persist the collaborator: "
            + canonical(
                {
                    "assignment": matter["documents"]["motion_to_amend"].get(
                        "assigned_user_id"
                    ),
                    "team": matter.get("team_members", []),
                    "variables": {
                        name: session_variables.get(name, "<undefined>")
                        for name in diagnostic_names
                    },
                }
            )
        )

    collaborator_browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    supervisor_browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    unrelated_browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    admin_browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    try:
        collaborator_browser.login(collaborator)
        collaborator_browser.open_interview(MATTER_INTERVIEW, session=session)
        collaborator_browser.wait_for_text(label)
        if "Manage team" in collaborator_browser.body_text():
            raise CertificationFailure("A collaborator was shown the team-management action")
        drive_rendered_workflow(
            collaborator_browser,
            label,
            collaborator_browser.action_url("Add team note"),
            {"clinic_internal_note_text": "Synthetic supervisor handoff note."},
            max_steps=args.max_steps,
        )
        collaborator_browser.screenshot("clinic-collaborator-workspace")

        unrelated_browser.login(unrelated)
        unrelated_browser.open_interview(MATTER_INTERVIEW, session=session)
        unrelated_browser.wait_for_text("You do not have access to this matter")
        unrelated_browser.screenshot("clinic-unassigned-access-denied")

        owner_action("Submit for review", {})
        matter = admin.variables(session)["clinic_matter"]
        if matter["documents"]["motion_to_amend"]["review_status"] != "ready_for_review":
            raise CertificationFailure("Student submission did not enter ready-for-review")

        supervisor_browser.login(supervisor)
        supervisor_browser.open_interview(MATTER_INTERVIEW, session=session)
        supervisor_browser.wait_for_text(label)
        request_changes_url = supervisor_browser.action_url_for_document(
            DOCUMENT_TITLES["motion_to_amend"], "Request changes"
        )
        drive_rendered_workflow(
            supervisor_browser,
            label,
            request_changes_url,
            {"clinic_review_comment": "Correct the synthetic filing detail."},
            max_steps=args.max_steps,
        )
        matter = admin.variables(session)["clinic_matter"]
        if matter["documents"]["motion_to_amend"]["review_status"] != "changes_requested":
            raise CertificationFailure("Supervisor change request did not persist")

        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        owner_browser.click_action_for_document(
            DOCUMENT_TITLES["motion_to_amend"], "Review or update answers"
        )
        owner_browser.wait_for_text("Review or update answers")
        owner_browser.screenshot("clinic-student-answer-review")
        owner_browser.click_action("Docket number")
        owner_browser.wait_for_variable("docket_number")
        corrected_docket_number = "CERT-DOCKET-REVISED"
        owner_browser.set_text("docket_number", corrected_docket_number)
        owner_browser.submit()
        owner_browser.wait_for_text("Review or update answers")
        if admin.variables(session).get("docket_number") != corrected_docket_number:
            raise CertificationFailure(
                "The clinic answer-review route did not update the canonical answer"
            )
        owner_browser.submit()
        owner_browser.wait.until(
            lambda driver: bool(
                driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card")
            )
        )
        regenerate_url = owner_browser.action_url_for_document(
            DOCUMENT_TITLES["motion_to_amend"], "Regenerate draft"
        )
        drive_rendered_workflow(
            owner_browser,
            label,
            regenerate_url,
            variables,
            max_steps=args.max_steps,
        )
        matter = admin.variables(session)["clinic_matter"]
        motion = matter["documents"]["motion_to_amend"]
        if len(motion["artifacts"]) != 2 or motion["review_status"] != "in_progress":
            raise CertificationFailure("Student revision did not create one new artifact")

        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        drive_rendered_workflow(
            owner_browser,
            label,
            owner_browser.action_url_for_document(
                DOCUMENT_TITLES["motion_to_amend"], "Submit for review"
            ),
            {},
            max_steps=args.max_steps,
        )
        supervisor_browser.open_interview(MATTER_INTERVIEW, session=session)
        supervisor_browser.wait_for_text(label)
        drive_rendered_workflow(
            supervisor_browser,
            label,
            supervisor_browser.action_url_for_document(
                DOCUMENT_TITLES["motion_to_amend"], "Approve"
            ),
            {"clinic_review_comment": "Approved in synthetic certification."},
            max_steps=args.max_steps,
        )
        supervisor_browser.open_interview(MATTER_INTERVIEW, session=session)
        supervisor_browser.wait_for_text(label)
        drive_rendered_workflow(
            supervisor_browser,
            label,
            supervisor_browser.action_url_for_document(
                DOCUMENT_TITLES["motion_to_amend"], "Ready for signature"
            ),
            {},
            max_steps=args.max_steps,
        )

        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        upload_url = owner_browser.action_url_for_document(
            DOCUMENT_TITLES["motion_to_amend"], "Add received file"
        )
        drive_rendered_workflow(
            owner_browser,
            label,
            upload_url,
            {
                "clinic_upload_purpose": "signed_copy",
                "clinic_upload_disposition": "not_applicable",
                "clinic_upload_filing_method": "not_recorded",
                "clinic_upload_court_outcome": "not_applicable",
                "clinic_upload_court_note": "Synthetic signed-copy check.",
            },
            max_steps=args.max_steps,
        )
        supervisor_browser.open_interview(MATTER_INTERVIEW, session=session)
        supervisor_browser.wait_for_text(label)
        verify_url = supervisor_browser.action_url_for_document(
            DOCUMENT_TITLES["motion_to_amend"], "Verify"
        )
        supervisor_browser.driver.get(verify_url)
        supervisor_browser.wait_for_text("Verify the received file")
        for variable in (
            "clinic_verify_document_identity",
            "clinic_verify_execution_marks",
            "clinic_verify_claimed_status",
        ):
            selector = (
                f"input[name='{encoded_name(variable)}'][value='True'], "
                f"input[name='{encoded_name(variable)}'][value='true']"
            )
            choice = supervisor_browser.wait.until(
                lambda driver, selector=selector: driver.find_element(
                    By.CSS_SELECTOR, selector
                )
            )
            if not choice.is_selected():
                supervisor_browser.driver.execute_script(
                    "arguments[0].click();", choice
                )
            time.sleep(0.2)
        supervisor_browser.submit()
        supervisor_browser.wait.until(
            lambda driver: bool(
                driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card")
            )
        )
        supervisor_browser.screenshot("clinic-supervisor-verified-file")

        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        for action_text in ("Add to court bundle", "Add to records bundle"):
            drive_rendered_workflow(
                owner_browser,
                label,
                owner_browser.action_url_for_document(
                    DOCUMENT_TITLES["motion_to_amend"], action_text
                ),
                {},
                max_steps=args.max_steps,
            )
            owner_browser.open_interview(MATTER_INTERVIEW, session=session)
            owner_browser.wait_for_text(label)
        for action_text in ("Build court-use bundle", "Build records bundle"):
            owner_browser.driver.get(owner_browser.action_url(action_text))
            owner_browser.wait_for_text("bundle ready")
            owner_browser.screenshot(
                "clinic-" + action_text.lower().replace(" ", "-")
            )
            owner_browser.submit()
            owner_browser.wait.until(
                lambda driver: bool(
                    driver.find_elements(By.CSS_SELECTOR, ".clinic-document-card")
                )
            )

        supervisor_browser.open_interview(MATTER_INTERVIEW, session=session)
        supervisor_browser.wait_for_text(label)
        drive_rendered_workflow(
            supervisor_browser,
            label,
            supervisor_browser.action_url("Close matter"),
            {"clinic_closure_reason": "administrative"},
            max_steps=args.max_steps,
        )
        matter = admin.variables(session)["clinic_matter"]
        if matter["overall_status"] != "closed":
            raise CertificationFailure("Administrative closure did not persist")
        owner_browser.open_interview(MATTER_INTERVIEW, session=session)
        owner_browser.wait_for_text(label)
        if any(
            action in owner_browser.body_text()
            for action in (
                "Review or update answers",
                "Regenerate draft",
                "Add received file",
            )
        ):
            raise CertificationFailure("Closed matter still exposed editing actions")
        owner_browser.screenshot("clinic-closed-read-only")

        admin_browser.login(clinic_admin)
        admin_browser.open_interview(MATTER_INTERVIEW, session=session)
        admin_browser.wait_for_text(label)
        admin_browser.driver.get(admin_browser.action_url("Reopen matter"))
        admin_browser.wait_for_text(label)
        matter = admin.variables(session)["clinic_matter"]
        if matter["overall_status"] != "active":
            raise CertificationFailure("Clinic administrator could not reopen the matter")
        admin_browser.screenshot("clinic-lifecycle-complete")
    finally:
        collaborator_browser.close()
        supervisor_browser.close()
        unrelated_browser.close()
        admin_browser.close()

    matter = admin.variables(session)["clinic_matter"]
    return {
        "status": "pass",
        "collaborator_user_id": collaborator.user_id,
        "supervisor_user_id": supervisor.user_id,
        "unrelated_user_id": unrelated.user_id,
        "clinic_admin_user_id": clinic_admin.user_id,
        "motion_artifact_count": len(
            matter["documents"]["motion_to_amend"]["artifacts"]
        ),
        "motion_review_status": matter["documents"]["motion_to_amend"][
            "review_status"
        ],
        "motion_execution_status": matter["documents"]["motion_to_amend"][
            "execution_status"
        ],
        "matter_status": matter["overall_status"],
        "internal_note_count": len(matter["internal_notes"]),
    }


def certify_documents(args: argparse.Namespace) -> dict[str, Any]:
    admin = AdminApi(args.server, args.api_key, args.timeout)
    for privilege in ("clinic_student", "clinic_supervisor", "clinic_admin"):
        admin.create_privilege(privilege)
    owner = admin.create_user("clinic_student", "document-owner")
    browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    api = Client(args.server, args.api_key, args.timeout)
    label = "CERT-ALL-DOCUMENTS-" + secrets.token_hex(3).upper()
    variables, cardinalities = load_comprehensive_scenario()
    results: dict[str, Any] = {}
    try:
        browser.login(owner)
        session = browser.create_matter(label, tuple(DOCUMENT_TITLES))
        browser.screenshot("clinic-all-documents-workspace")
        for document_id in WORKFLOW_REPRESENTATIVES:
            browser.open_interview(MATTER_INTERVIEW, session=session)
            browser.wait_for_text(label)
            action_url = browser.action_url_for_document(
                DOCUMENT_TITLES[document_id],
                "Answer questions and create draft",
            )
            results[document_id] = drive_rendered_workflow(
                browser,
                label,
                action_url,
                variables,
                max_steps=args.max_steps,
            )
            matter = admin.variables(session).get("clinic_matter", {})
            artifact_count = len(
                matter.get("documents", {}).get(document_id, {}).get("artifacts", [])
            )
            if artifact_count < 1:
                raise CertificationFailure(
                    f"{document_id} returned to the workspace without a stored artifact; "
                    f"render trace: {canonical(results[document_id])[:2000]}"
                )
            results[document_id]["artifact_count"] = artifact_count
            print(
                canonical(
                    {
                        "artifact_count": artifact_count,
                        "document": document_id,
                        "seconds": results[document_id]["seconds"],
                        "status": "pass",
                        "steps": results[document_id]["steps"],
                    }
                ),
                flush=True,
            )

        matter = admin.variables(session)["clinic_matter"]
        missing = [
            document_id
            for document_id in DOCUMENT_TITLES
            if not matter["documents"][document_id]["artifacts"]
        ]
        if missing:
            raise CertificationFailure(
                "Selected documents without a generated artifact: " + ", ".join(missing)
            )
        browser.open_interview(MATTER_INTERVIEW, session=session)
        browser.wait_for_text(label)
        browser.screenshot("clinic-all-documents-complete")
        lifecycle = certify_collaboration_lifecycle(
            args,
            admin,
            browser,
            session,
            label,
            variables,
        )
        return {
            "status": "pass",
            "matter_label": label,
            "session": session,
            "owner_user_id": owner.user_id,
            "documents": results,
            "lifecycle": lifecycle,
            "artifact_counts": {
                document_id: len(matter["documents"][document_id]["artifacts"])
                for document_id in DOCUMENT_TITLES
            },
        }
    finally:
        browser.close()


def certify_lifecycle_only(args: argparse.Namespace) -> dict[str, Any]:
    """Build one small matter and run only collaboration lifecycle checks."""

    admin = AdminApi(args.server, args.api_key, args.timeout)
    for privilege in ("clinic_student", "clinic_supervisor", "clinic_admin"):
        admin.create_privilege(privilege)
    owner = admin.create_user("clinic_student", "lifecycle-owner")
    browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    variables, _ = load_comprehensive_scenario()
    label = "CERT-LIFECYCLE-" + secrets.token_hex(3).upper()
    try:
        browser.login(owner)
        session = browser.create_matter(label, ("motion_to_amend",))
        browser.open_interview(MATTER_INTERVIEW, session=session)
        browser.wait_for_text(label)
        drive_rendered_workflow(
            browser,
            label,
            browser.action_url_for_document(
                DOCUMENT_TITLES["motion_to_amend"], "Answer questions and create draft"
            ),
            variables,
            max_steps=args.max_steps,
        )
        return {
            "status": "pass",
            "phase": "lifecycle",
            "matter_label": label,
            "session": session,
            "lifecycle": certify_collaboration_lifecycle(
                args, admin, browser, session, label, variables
            ),
        }
    finally:
        browser.close()


def certify_visible_action_routes(args: argparse.Namespace) -> dict[str, Any]:
    """Click every baseline dashboard and matter action in rendered pages."""

    admin = AdminApi(args.server, args.api_key, args.timeout)
    for privilege in ("clinic_student", "clinic_supervisor", "clinic_admin"):
        admin.create_privilege(privilege)
    owner = admin.create_user("clinic_student", "route-owner")
    browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    label = "CERT-ROUTES-" + secrets.token_hex(3).upper()
    checked: list[dict[str, str]] = []

    def record(route: str, expected: str) -> None:
        browser.wait_for_text(expected)
        browser.assert_healthy_page(route)
        checked.append(
            {
                "route": route,
                "expected": expected,
                "url": browser.driver.current_url,
            }
        )

    try:
        browser.login(owner)
        browser.open_interview(DASHBOARD_INTERVIEW)
        record("Dashboard first-use empty state", "No clinic matters yet")
        if "Create your first matter" not in browser.body_text():
            raise CertificationFailure("First-use dashboard did not expose its primary action")
        browser.screenshot("clinic-dashboard-first-use-empty")

        browser.click_action("Needs review")
        record("First-use dashboard remains primary under review filter", "No clinic matters yet")
        browser.click_action("All assigned")
        record("Dashboard return to all from review", "No clinic matters yet")
        browser.click_action("Closed")
        record("First-use dashboard remains primary under closed filter", "No clinic matters yet")
        browser.click_action("All assigned")
        record("Dashboard return to all from closed", "No clinic matters yet")

        session = browser.create_matter(label, ("joint_petition",))
        record("Dashboard Create matter", label)
        workspace_text = browser.body_text()
        browser.screenshot("clinic-route-workspace-navigation")
        if any(
            "Close matter" in (link.text or link.get_attribute("textContent") or "")
            for link in browser.driver.find_elements(By.TAG_NAME, "a")
        ):
            raise CertificationFailure(
                "A student owner was shown the supervisor-only close action"
            )
        for expected_navigation in (
            "Matter setup",
            "Matter overview",
            "Document work",
            "Questions and draft",
            "Review and revisions",
            "Signature and filing",
            "Bundles and closeout",
            "Workspace progress",
        ):
            if expected_navigation.casefold() not in workspace_text.casefold():
                raise CertificationFailure(
                    "Matter workspace did not render navigation/progress label "
                    f"{expected_navigation!r}; page contains {workspace_text[:2200]!r}"
                )

        browser.click_action("Caseload dashboard")
        record("Matter Caseload dashboard", label)
        browser.click_action("Needs review")
        record("Populated dashboard needs-review filter", "No matters need review")
        browser.click_action("View all matters")
        record("Populated dashboard View all matters", label)
        browser.click_action("Closed")
        record("Populated dashboard closed filter", "No closed matters")
        browser.click_action("View all matters")
        record("Populated dashboard return to all", label)

        matter_routes = (
            ("Matter details", "Update matter details"),
            ("Edit filing plan", "What documents should this matter prepare?"),
            ("Manage team", "Add or update a matter team member"),
            ("Add team note", "Add a team note"),
            ("Build court-use bundle", "No files are ready for this bundle"),
            ("Build records bundle", "No files are ready for this bundle"),
        )
        for action_text, expected in matter_routes:
            browser.open_interview(MATTER_INTERVIEW, session=session)
            browser.wait_for_text(label)
            browser.click_action(action_text)
            record(action_text, expected)
            if "Return to matter" not in browser.body_text():
                raise CertificationFailure(
                    f"Route {action_text!r} did not expose a return path"
                )
            browser.return_to_matter(label)

        for action_text, expected in (
            ("Add received file", "Add a received file"),
            ("Assign", "Assign Joint petition for divorce"),
        ):
            browser.open_interview(MATTER_INTERVIEW, session=session)
            browser.wait_for_text(label)
            browser.click_action_for_document(
                DOCUMENT_TITLES["joint_petition"], action_text
            )
            record(action_text, expected)
            if "Return to matter" not in browser.body_text():
                raise CertificationFailure(
                    f"Document route {action_text!r} did not expose a return path"
                )
            browser.return_to_matter(label)

        browser.open_interview(MATTER_INTERVIEW, session=session)
        browser.click_action_for_document(
            DOCUMENT_TITLES["joint_petition"],
            "Answer questions and create draft",
        )
        browser.wait.until(
            lambda driver: bool(driver.find_elements(By.CSS_SELECTOR, ".clinic-work-context"))
        )
        record("Answer questions and create draft", "Return to matter")
        if "Questions and draft" not in browser.body_text():
            raise CertificationFailure("Document questions did not retain the clinic navigation rail")
        browser.screenshot("clinic-route-document-progress")
        browser.return_to_matter(label)

        for destination in ("court", "records"):
            add_label = f"Add to {destination} bundle"
            remove_label = f"Remove from {destination} bundle"
            browser.open_interview(MATTER_INTERVIEW, session=session)
            browser.click_action_for_document(DOCUMENT_TITLES["joint_petition"], add_label)
            record(add_label, remove_label)
            browser.click_action_for_document(DOCUMENT_TITLES["joint_petition"], remove_label)
            record(remove_label, add_label)

        return {
            "status": "pass",
            "phase": "routes",
            "matter_label": label,
            "session": session,
            "checked_route_count": len(checked),
            "checked_routes": checked,
        }
    finally:
        browser.close()


def certify_answer_review_routes(args: argparse.Namespace) -> dict[str, Any]:
    """Prove the special care/custody and financial answer-review routes."""

    admin = AdminApi(args.server, args.api_key, args.timeout)
    for privilege in ("clinic_student", "clinic_supervisor", "clinic_admin"):
        admin.create_privilege(privilege)
    owner = admin.create_user("clinic_student", "answer-review-owner")
    browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    variables, _ = load_comprehensive_scenario()
    label = "CERT-ANSWER-REVIEW-" + secrets.token_hex(3).upper()
    selected = ("care_or_custody_affidavit", "financial_statement_party_a")
    planned = ("joint_petition",) + selected
    try:
        browser.login(owner)
        session = browser.create_matter(label, planned)
        for document_id in selected:
            browser.open_interview(MATTER_INTERVIEW, session=session)
            browser.wait_for_text(label)
            drive_rendered_workflow(
                browser,
                label,
                browser.action_url_for_document(
                    DOCUMENT_TITLES[document_id], "Answer questions and create draft"
                ),
                variables,
                max_steps=args.max_steps,
            )

        browser.open_interview(MATTER_INTERVIEW, session=session)
        browser.wait_for_text(label)
        browser.click_action_for_document(
            DOCUMENT_TITLES["care_or_custody_affidavit"],
            "Review or update answers",
        )
        browser.wait_for_text("First child's current address")
        browser.click_action("First child's name")
        browser.wait_for_variable("children[0].name.first")
        drive_rendered_workflow(
            browser,
            label,
            None,
            variables,
            max_steps=args.max_steps,
        )
        browser.wait_for_text("Regenerate draft")

        browser.open_interview(MATTER_INTERVIEW, session=session)
        browser.wait_for_text(label)
        browser.click_action_for_document(
            DOCUMENT_TITLES["financial_statement_party_a"],
            "Review or update answers",
        )
        for expected_label in (
            "Income entries",
            "Short-form expense entries",
            "Motor vehicles",
            "Liabilities",
            "Self-employment schedule",
            "Rental-property schedule",
        ):
            browser.wait_for_text(expected_label)
        browser.screenshot("clinic-special-answer-review-routes")
        browser.submit()
        browser.wait_for_text(label)
        browser.action_url_for_document(
            DOCUMENT_TITLES["financial_statement_party_a"], "Regenerate draft"
        )

        matter = admin.variables(session)["clinic_matter"]
        return {
            "status": "pass",
            "phase": "answer-review",
            "matter_label": label,
            "session": session,
            "artifact_counts": {
                document_id: len(matter["documents"][document_id]["artifacts"])
                for document_id in selected
            },
            "reviewed_documents": list(selected),
        }
    finally:
        browser.close()


def certify_existing_session_after_restart(args: argparse.Namespace) -> dict[str, Any]:
    """Prove a persisted matter and caseload views after a container restart."""

    if not args.session:
        raise CertificationFailure("--session is required for the restart phase")
    admin = AdminApi(args.server, args.api_key, args.timeout)
    admin.create_privilege("clinic_admin")
    clinic_admin = admin.create_user("clinic_admin", "restart-administrator")
    matter = admin.variables(args.session)["clinic_matter"]
    label = matter["safe_label"]
    browser = ClinicBrowser(args.server, args.artifacts, args.timeout)
    matter_open_seconds: list[float] = []
    dashboard_seconds: list[float] = []
    filter_seconds: list[float] = []
    try:
        browser.login(clinic_admin)
        for _ in range(10):
            started = time.monotonic()
            browser.open_interview(MATTER_INTERVIEW, session=args.session)
            browser.wait_for_text(label)
            matter_open_seconds.append(time.monotonic() - started)
        browser.screenshot("clinic-restart-recovery")

        for _ in range(10):
            started = time.monotonic()
            browser.open_interview(DASHBOARD_INTERVIEW)
            browser.wait_for_text("Clinic divorce matters")
            browser.wait_for_text(label)
            dashboard_seconds.append(time.monotonic() - started)
        browser.screenshot("clinic-caseload-all-assigned")

        for action_text in ("Needs review", "Closed"):
            started = time.monotonic()
            browser.driver.get(browser.action_url(action_text))
            browser.wait_for_text("Clinic divorce matters")
            filter_seconds.append(time.monotonic() - started)
            if label in browser.body_text():
                raise CertificationFailure(
                    f"Active approved matter appeared in the {action_text!r} filter"
                )
            started = time.monotonic()
            browser.driver.get(browser.action_url("All assigned"))
            browser.wait_for_text(label)
            filter_seconds.append(time.monotonic() - started)
        browser.screenshot("clinic-caseload-filter-recovery")
    finally:
        browser.close()

    motion = matter["documents"]["motion_to_amend"]
    runtime_performance = {
        "sample_count": 10,
        "matter_open_p50_seconds": round(statistics.median(matter_open_seconds), 4),
        "matter_open_p95_seconds": round(sorted(matter_open_seconds)[-1], 4),
        "dashboard_p50_seconds": round(statistics.median(dashboard_seconds), 4),
        "dashboard_p95_seconds": round(sorted(dashboard_seconds)[-1], 4),
        "filter_sample_count": len(filter_seconds),
        "filter_p50_seconds": round(statistics.median(filter_seconds), 4),
        "filter_p95_seconds": round(sorted(filter_seconds)[-1], 4),
    }
    if runtime_performance["matter_open_p95_seconds"] >= 2.0:
        raise CertificationFailure("Matter-open runtime budget exceeded")
    if runtime_performance["dashboard_p95_seconds"] >= 2.0:
        raise CertificationFailure("Dashboard runtime budget exceeded")
    if runtime_performance["filter_p95_seconds"] >= 1.5:
        raise CertificationFailure("Dashboard-filter runtime budget exceeded")
    return {
        "status": "pass",
        "phase": "restart",
        "session": args.session,
        "matter_label": label,
        "matter_status": matter["overall_status"],
        "team_roles": sorted(
            member["matter_role"]
            for member in matter["team_members"]
            if member.get("active")
        ),
        "internal_note_count": len(matter["internal_notes"]),
        "motion_artifact_count": len(motion["artifacts"]),
        "motion_review_status": motion["review_status"],
        "motion_execution_status": motion["execution_status"],
        "motion_bundle_destinations": sorted(motion["bundle_destinations"]),
        "runtime_performance": runtime_performance,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument(
        "--phase",
        choices=("all", "lifecycle", "answer-review", "routes", "restart"),
        default="all",
    )
    parser.add_argument("--session")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.phase == "lifecycle":
            report = certify_lifecycle_only(args)
        elif args.phase == "answer-review":
            report = certify_answer_review_routes(args)
        elif args.phase == "routes":
            report = certify_visible_action_routes(args)
        elif args.phase == "restart":
            report = certify_existing_session_after_restart(args)
        else:
            report = certify_documents(args)
    except Exception as exc:  # strict command-line boundary
        report = {
            "status": "fail",
            "failure_type": type(exc).__name__,
            "failure": str(exc),
            "traceback": traceback.format_exc(),
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(canonical(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
