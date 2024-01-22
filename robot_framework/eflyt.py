
from datetime import date

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select

from robot_framework import config


ALLOWED_CASE_TYPES = (
    "Logivært",
    "Boligselskab",
    "For sent anmeldt"
)


def login(orchestrator_connection: OrchestratorConnection) -> webdriver.Chrome:
    """Opens a browser and logs in to Eflyt.

    Args:
        orchestrator_connection: The connection to Orchestrator.

    Returns:
        A selenium browser object.
    """
    eflyt_creds = orchestrator_connection.get_credential(config.EFLYT_CREDS)

    browser = webdriver.Chrome()
    browser.maximize_window()
    browser.get("https://notuskommunal.scandihealth.net/")

    user_field = browser.find_element(By.ID, "Login1_UserName")
    user_field.send_keys(eflyt_creds.username)

    pass_field = browser.find_element(By.ID, "Login1_Password")
    pass_field.send_keys(eflyt_creds.password)

    browser.find_element(By.ID, "Login1_LoginImageButton").click()

    browser.get("https://notuskommunal.scandihealth.net/web/SearchResulteFlyt.aspx")

    return browser


def search_cases(browser: webdriver.Chrome) -> None:
    """Apply the correct filters in Eflyt and search the case list.

    Args:
        browser: The webdriver browser object.
    """
    sagstilstand_select = Select(browser.find_element(By.ID, "ctl00_ContentPlaceHolder1_SearchControl_ddlTilstand"))
    sagstilstand_select.select_by_visible_text("Ubehandlet")

    search_date = date.today().strftime("%d%m%Y")
    date_input = browser.find_element(By.ID, "ctl00_ContentPlaceHolder1_SearchControl_txtFlytteEndDato")
    date_input.send_keys(search_date)

    search_button = browser.find_element(By.ID, "ctl00_ContentPlaceHolder1_SearchControl_btnSearch")
    search_button.click()


def extract_cases(browser: webdriver.Chrome) -> list[str]:
    """Extract and filter cases from the case table.

    Args:
        browser: The webdriver browser object.

    Returns:
        A list of filtered case objects.
    """
    table = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_GridViewSearchResult")
    rows = table.find_elements(By.TAG_NAME, "tr")

    # remove header row
    rows.pop(0)

    cases = []
    for row in rows:
        case_number = row.find_element(By.XPATH, "td[4]").text
        case_types_text = row.find_element(By.XPATH, "td[5]").text

        # If the case types ends with '...' we need to get the title instead
        if case_types_text.endswith("..."):
            case_types_text = row.find_element(By.XPATH, "td[5]").get_attribute("Title")

        case_types = case_types_text.split(", ")

        # Check if there are any case types other than the allowed ones
        for case_type in case_types:
            if case_type not in ALLOWED_CASE_TYPES:
                break
        else:
            cases.append(case_number)

    return cases


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

    open_case(browser, case_number)

    # Check if address has been handled earlier in the run
    if check_address(browser, prev_addresses):
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Duplikeret adresse")
        return

    beboer_count = count_beboere(browser)

    if beboer_count != 0:
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Beboere på adressen")
        return

    room_count = get_room_count(browser)

    applicants = get_applicants(browser)

    if room_count >= len(applicants):
        approve_case(browser)
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sag godkendt.")
        return

    # Check for parent+child in 1 room
    if room_count == 1 and len(applicants) == 2:
        is_child = any(get_age(cpr) < 15 for cpr in applicants)
        if is_child:
            approve_case(browser)
            orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sag godkendt.")
            return

    orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over: Flere ansøgere end rum.")


def check_queue(case_number: str, orchestrator_connection: OrchestratorConnection) -> bool:
    """Check if a case has been handled before by checking the job queue in Orchestrator.

    Args:
        case: The case to check.
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


def count_beboere(browser: webdriver.Chrome) -> int:
    """Count the number of beboere living on the address.

    Args:
        browser: The webdriver browser object.

    Returns:
        The number of beboere on the address.
    """
    change_tab(browser, 1)
    beboer_table = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_becPersonTab_GridViewBeboere")
    rows = beboer_table.find_elements(By.TAG_NAME, "tr")

    # Remove header
    rows.pop(0)

    return len(rows)


def get_room_count(browser: webdriver.Chrome) -> int:
    """Get the number of rooms on the address.

    Args:
        browser: The webdriver browser object.

    Returns:
        The number of rooms on the address.
    """
    area_room_text = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab6_lblAreaText").text
    room_text = area_room_text.split("/")[1]
    return int(room_text)


def get_applicants(browser: webdriver.Chrome) -> list[str]:
    """Get a list of applicants' cpr numbers from the applicant table.

    Args:
        browser: The webdriver browser object.

    Returns:
        A list of cpr numbers.
    """
    table = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_GridViewMovingPersons")
    rows = table.find_elements(By.TAG_NAME, "tr")

    # Remove header row
    rows.pop(0)

    cpr_list = []

    for row in rows:
        cpr = row.find_element(By.XPATH, "td[2]/a[2]").text
        cpr_list.append(cpr)

    return cpr_list


def approve_case(browser: webdriver.Chrome):
    """Approve the case and add a note about it.

    Args:
        browser: _description_
    """
    change_tab(browser, 0)

    # Set note
    create_note(browser, f"{date.today()} Besked fra Robot: Automatisk godkendt.")

    # Click 'Godkend'
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnGodkend").click()

    # Click 'OK' in popup
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnApproveYes").click()

    # Click 'Godkend' personer
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_stcPersonTab1_btnGodkendAlle").click()


def get_age(cpr: str) -> int:
    """Get the age of a person based on their cpr number
    assuming they are between 0-99 years old.

    Args:
        cpr: The cpr number in the format 'ddmmyy-xxxx' or 'ddmmyyxxxx'.

    Returns:
        The age based on the cpr number.
    """
    day = int(cpr[0:2])
    month = int(cpr[2:4])
    year = int(cpr[4:6]) + 2000

    birthdate = date(year, month, day)
    current_date = date.today()

    # If the birthdate is in the future revert it back 100 years
    if birthdate > current_date:
        birthdate = date(year-100, month, day)

    age = current_date.year - birthdate.year - ((current_date.month, current_date.day) < (birthdate.month, birthdate.day))

    return age


def open_case(browser: webdriver.Chrome, case_number: str):
    """Open a case by searching for it's case number.

    Args:
        browser: The webdriver browser object.
        case: The case to open.
    """
    # The id for both the search field and search button changes based on the current view hence the weird selectors.
    case_input = browser.find_element(By.XPATH, '//input[contains(@id, "earchControl_txtSagNr")]')
    case_input.clear()
    case_input.send_keys(case_number)

    browser.find_element(By.XPATH, '//input[contains(@id, "earchControl_btnSearch")]').click()


def change_tab(browser: webdriver.Chrome, tab_index: int):
    """Change the tab in the case view e.g. 'Sagslog', 'Breve'.

    Args:
        browser: The webdriver browser object.
        tab_index: The zero-based index of the tab to select.
    """
    browser.execute_script(f"__doPostBack('ctl00$ContentPlaceHolder2$ptFanePerson$ImgJournalMap','{tab_index}')")


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
