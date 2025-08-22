"""This module contains the main process of the robot."""

import os
from datetime import date

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from itk_dev_shared_components.eflyt import eflyt_login, eflyt_search
import itk_dev_event_log

from robot_framework import eflyt, config


def process(prev_addresses: list[str], orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
    orchestrator_connection.log_trace("Running process.")

    event_log_conn_String = orchestrator_connection.get_constant(config.EVENT_LOG)
    itk_dev_event_log.setup_logging(event_log_conn_String.value)

    credentials = orchestrator_connection.get_credential(config.EFLYT_CREDS)
    browser = eflyt_login.login(credentials.username, credentials.password)

    eflyt_search.search(browser, to_date=date.today(), case_state="Ubehandlet")
    cases = eflyt_search.extract_cases(browser)
    cases = eflyt.filter_cases(cases)

    for case in cases:
        result = eflyt.handle_case(browser, case.case_number, prev_addresses, orchestrator_connection)
        if result == eflyt.CaseResult.APPROVED:
            itk_dev_event_log.emit("Eflyt godkendelse af logiværtsflytninger", "Sag godkendt")
        elif result == eflyt.CaseResult.NOT_APPROVED:
            itk_dev_event_log.emit("Eflyt godkendelse af logiværtsflytninger", "Sag sprunget over")


if __name__ == '__main__':
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Eflyt Test", conn_string, crypto_key, "")
    process([], oc)
