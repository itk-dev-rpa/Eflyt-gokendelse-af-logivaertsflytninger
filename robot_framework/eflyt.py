"""This module handles all logic related to the Eflyt system."""

from datetime import date

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus
from selenium import webdriver
from selenium.webdriver.common.by import By
from itk_dev_shared_components.misc import cpr_util
from itk_dev_shared_components.eflyt import eflyt_case, eflyt_search
from itk_dev_shared_components.eflyt.eflyt_case import Case

from robot_framework import config


def filter_cases(cases: list[Case]) -> list[Case]:
    """Filter cases on case types and return filtered list.

    Args:
        cases: List of cases

    Return:
        List of filtered cases
    """
    allowed_case_types = (
        "Logivært",
        "Boligselskab",
        "For sent anmeldt"
    )

    filtered_cases = [
        case for case in cases
        if all(case_type in allowed_case_types for case_type in case.case_types)
    ]

    return filtered_cases


def handle_case(browser: webdriver.Chrome, case_number: str, prev_addresses: list[str], orchestrator_connection: OrchestratorConnection) -> None:
    """Handle a single case with all steps included.

    Args:
        browser: The webdriver browser object.
        case: The case to handle.
        orchestrator_connection: The connection to Orchestrator.
    """
    if not check_queue(case_number, orchestrator_connection):
        return

    # Create a queue element to indicate the case is being handled
    queue_element = orchestrator_connection.create_queue_element(config.QUEUE_NAME, reference=case_number)
    orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.IN_PROGRESS)

    orchestrator_connection.log_info(f"Beginning case: {case_number}")

    eflyt_search.open_case(browser, case_number)

    # Check if address has been handled earlier in the run
    if check_address(browser, prev_addresses):
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Duplikeret adresse")
        return

    beboer_count = len(eflyt_case.get_beboere(browser))

    if beboer_count != 0:
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Beboere på adressen")
        return

    room_count = eflyt_case.get_room_count(browser)

    applicants = eflyt_case.get_applicants(browser)

    # Check if all applicants are younger than 19
    if all(cpr_util.get_age(applicant.cpr) < 19 for applicant in applicants):
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Ingen ansøgere over 18.")
        return

    if room_count >= len(applicants):
        approve_case(browser)
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sag godkendt.")
        return

    # Check for parent+child in 1 room
    if room_count == 1 and len(applicants) == 2:
        if any(cpr_util.get_age(applicant.cpr) < 15 for applicant in applicants):
            approve_case(browser)
            orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sag godkendt.")
            return

    orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Flere ansøgere end rum.")


def check_queue(case_number: str, orchestrator_connection: OrchestratorConnection) -> bool:
    """Check if a case has been handled before by checking the job queue in Orchestrator.

    Args:
        case: The case number to check.
        orchestrator_connection: The connection to Orchestrator.

    Return:
        bool: True if the element should be handled, False if it should be skipped.
    """
    queue_elements = orchestrator_connection.get_queue_elements(queue_name=config.QUEUE_NAME, reference=case_number)

    if len(queue_elements) == 0:
        return True

    # If the case has been tried more than once before skip it
    if len(queue_elements) > 1:
        orchestrator_connection.log_info("Skipping: Case has failed in the past.")
        return False

    # If it has been marked as done, skip it
    if queue_elements[0].status == QueueStatus.DONE:
        orchestrator_connection.log_info("Skipping: Case already marked as done.")
        return False

    return True


def approve_case(browser: webdriver.Chrome):
    """Approve the case and add a note about it.

    Args:
        browser: _description_
    """
    eflyt_case.change_tab(browser, 0)

    # Set note
    create_note(browser, f"{date.today()} Besked fra Robot: Automatisk godkendt.")

    # Click 'Godkend'
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnGodkend").click()

    # Click 'OK' in popup
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnApproveYes").click()

    # Click 'Godkend' personer
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnGodkendAlle").click()


def create_note(browser: webdriver.Chrome, note_text: str):
    """Create a note on the case."""
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_ncPersonTab_ButtonVisOpdater").click()

    text_area = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_ncPersonTab_txtVisOpdaterNote")

    text_area.send_keys(note_text)
    text_area.send_keys("\n\n")

    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_ncPersonTab_btnLongNoteUpdater").click()


def check_address(browser: webdriver.Chrome, prev_addresses: list[str]) -> bool:
    """Check if the "to" address has been handled in another case in this run.
    Also add the address to the list of handled addresses.

    Args:
        browser: The webdriver browser object.
        prev_addresses: A list of previously handled addresses.

    Returns:
        True if the address is on the list and the case should be skipped.
    """
    address = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_lblTiltxt").text

    if address in prev_addresses:
        return True

    prev_addresses.append(address)
    return False
