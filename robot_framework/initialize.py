"""This module defines any initial processes to run when the robot starts."""

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection


def initialize(orchestrator_connection: OrchestratorConnection) -> list:
    """Do all custom startup initializations of the robot."""
    orchestrator_connection.log_trace("Initializing.")

    # Create a list for remembering addresses which have been handled.
    prev_addresses = []
    return prev_addresses
