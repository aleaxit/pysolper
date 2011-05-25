# -*- coding: utf-8 -*-
"""
    models
    ~~~~~~~~~~~~~~~~~~~~

    Top-level models for the entire app.

    :copyright: 2011 by Google, Inc.
    :license: Apache 2.0, see LICENSE for more details.
"""

from google.appengine.ext import db
from google.appengine.ext import blobstore

USER_ROLES = ('Permit Approver', 'Applicant', 'Spectator')
# These may be ordered lexicographically, the first three characters 
# will be stripped before display. 
CASE_STATES = ('00 Incomplete', '10 Submitted', 
               '20 Commented', '30 Approved', '40 Denied')
CASE_ACTIONS = ('Create', 'Update', 'Submit', 'Comment', 'Approve', 'Deny')

class User(db.Model):
    email = db.EmailProperty(required=True)
    role = db.StringProperty(choices=USER_ROLES, required=False)

    @classmethod
    def get_by_email(cls, email):
        return cls.all().filter('email = ', email).get()

class Case(db.Model):
    address = db.StringProperty(required=True)
    creation_date = db.DateProperty(required=True, auto_now_add=True)
    owner = db.ReferenceProperty(User, required=True)
    state = db.StringProperty(required=True, choices=CASE_STATES)
    email_listeners = db.StringListProperty()
    
    @classmethod
    def query_by_owner(cls, user):
        """Returns a db.Query."""
        return cls.all().filter('owner = ', user)

    @classmethod
    def create(cls, owner, **k):
        case = cls(state=CASE_STATES[0], owner=owner, **k)
        case.put()
        first_action = CaseAction(action=CASE_ACTIONS[0], 
                                  case=case, actor=owner)
        first_action.put()
        return case

    @property
    def visible_state(self):
        return self.state[3:]

    @property
    def latest_action(self):
        return CaseAction.query_by_case(self).order('-timestamp').get()

    @property
    def last_modified(self):
        return self.latest_action.timestamp


class CaseAction(db.Model):
    """Immutable once created."""
    action = db.StringProperty(required=True, choices=CASE_ACTIONS)
    case = db.ReferenceProperty(Case, required=True)
    actor = db.ReferenceProperty(User, required=True)
    timestamp = db.DateTimeProperty(auto_now_add=True, required=True)
    notes = db.TextProperty(required=False)

    @classmethod
    def query_by_case(cls, case):
        return cls.all().filter('case = ', case)

class Document(db.Model):
    """Going to be immutable once they are created."""
    filename = db.StringProperty(required=True)
    action = db.ReferenceProperty(CaseAction, required=True)
    uploaded_by = db.ReferenceProperty(User, required=True)
    uploaded_time = db.DateTimeProperty(required=True, auto_now_add=True)
    # Either comments or notes or both will be present.
    contents = blobstore.BlobReferenceProperty(required=False)  
    notes = db.TextProperty(required=False)

