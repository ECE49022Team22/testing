"""In-memory stand-in for a note-python Notecard object (anything with .Transaction)."""

import copy


class FakeNotecard:
    """Records every JSON request and replies with canned responses.

    responses maps a "req" name (e.g. "note.changes") to either a response dict
    or a list of response dicts consumed one per call (last one repeats).
    Unconfigured requests get {}.
    """

    def __init__(self, responses=None):
        self.requests = []
        self._responses = dict(responses or {})

    def set_response(self, req_name, response):
        self._responses[req_name] = response

    def Transaction(self, req, lock=True):
        self.requests.append(copy.deepcopy(req))
        rsp = self._responses.get(req.get("req"), {})
        if isinstance(rsp, list):
            rsp = rsp.pop(0) if len(rsp) > 1 else rsp[0]
        return copy.deepcopy(rsp)

    @property
    def last(self):
        return self.requests[-1]
