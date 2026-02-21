# Universal Ping Plugin for Galactic Core

def pulse(config):
    """
    Standard pulse function called by the Core heartbeat.
    Returns a status string to be displayed in the UI.
    """
    # This is where a real plugin would check emails, scan files, etc.
    return "PONG"
