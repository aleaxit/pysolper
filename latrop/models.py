# -*- coding: utf-8 -*-
"""
    models
    ~~~~~~~~~~~~~~~~~~~~

    Top-level models for the entire app.

    :copyright: 2011 by Google, Inc.
    :license: Apache 2.0, see LICENSE for more details.
"""

# standard Python library imports
import datetime
import logging
import urllib

# App Engine imports
from google.appengine.ext import db
from google.appengine.ext import blobstore
from django.utils import simplejson

# local imports
import timesince

# roles the system distinguishes for each user
USER_ROLES = ('Applicant', 'Permit Approver')

# Cases may be ordered lexicographically by state, the first three characters
# of the state string (value in the dict) will be stripped before display.
CASE_STATES = {'incomplete': '00 Incomplete',
               'submitted': '10 Submitted For Review',
	       'under_review': '20 Review Under Way',
	       'needs_work': '30 Needs Work',
	       'approved': '40 Approved',
	       'denied': '50 Rejected',
	      }

# the case states in which an applicant can upload files and/or notes
APPLICANT_EDITABLE = set(CASE_STATES[x]
                         for x in 'incomplete submitted needs_work'.split())

# the kind of actions that cause a case to change
CASE_ACTIONS = ('Create', 'Update', 'Submit',
                'Review', 'Reassign', 'Comment', 'Approve', 'Deny')

# documents an applicant must upload to submit a case for approver review
PURPOSES = (
    'Site Diagram',
    'Electrical Diagram',
    'Diagram Notes'
    )


class ModelEncoder(simplejson.JSONEncoder):
    def default(self, obj):
        """Allow JSON encoding of a db.Model instance."""
	try:
	    return obj.json()
	except (AttributeError, TypeError):
            return simplejson.JSONEncoder.default(self, obj)


class JurisModel(db.Model):
    """A db.Model with a jurisdiction attached (abstract base class)."""
    juris = db.StringProperty(required=True)
    timestamp = db.DateTimeProperty(auto_now_add=True, required=True)

    @classmethod
    def get_all(cls):
        return cls.all().order('-timestamp')

    @property
    def timesince(self):
	"""Readable form for this object's timestamp."""
        return timesince.timesince(self.timestamp)


class LatropMessage(JurisModel):
    """A message received by the latrop."""
    msg = db.StringProperty(required=True)

    @classmethod
    def create(cls, juris, msg):
        obj = cls(juris=juris, msg=msg)
        obj.put()


# TODO: the other models must be changed to be appropriate for the latrop
# (mandatory juris, factories, different methods, and so on).

class User(JurisModel):
    """A user of this permiting application."""
    # TODO: add authentication mechanisms / tokens
    # email works as the "primary key" to identify a user
    email = db.EmailProperty(required=True)
    # application logic ensures a role gets assigned when a new user logs in
    # for the first time, but the User object is first created w/o a role
    role = db.StringProperty(choices=USER_ROLES, required=False)

    def json(self):
        """Return JSON-serializable form."""
	return {'cls': 'User', 'email': self.email, 'role': self.role}

    @classmethod
    def get_by_email(cls, email):
        return cls.all().filter('email = ', email).get()

    @property
    def can_upload(self):
        return self.role == 'Applicant'

    @property
    def can_approve(self):
        return self.role == 'Permit Approver'

    def __eq__(self, other):
        return other is not None and self.email == other.email

    def __ne__(self, other):
        return other is None or self.email != other.email


class Case(JurisModel):
    """A project for which approval is requested."""
    address = db.StringProperty(required=True)
    creation_date = db.DateProperty(required=True, auto_now_add=True)
    owner = db.ReferenceProperty(User, required=True)
    state = db.StringProperty(required=True, choices=CASE_STATES.values())

    def json(self):
        """Return JSON-serializable form."""
	return {'cls': 'Case', 'address': self.address,
	        'owner': self.owner.json(), 'state': self.state}

    @classmethod
    def query_by_owner(cls, user):
        """Returns a db.Query for all cases owned by this user."""
        return cls.all().filter('owner = ', user)

    @classmethod
    def query_under_review(cls):
        """Returns a db.Query for all cases under review."""
        return cls.all().filter('state = ', CASE_STATES['under_review'])

    @classmethod
    def query_submitted(cls):
        """Returns a db.Query for all cases in the submitted state."""
        return cls.all().filter('state = ', CASE_STATES['submitted'])

    @classmethod
    def reviewed_by(cls, user):
       """Returns two lists: cases being reviewed by the user vs by other users."""
       these_cases, other_cases = [], []
       for case in cls.query_under_review().run():
           if case.reviewer == user:
	       these_cases.append(case)
	   else:
	       other_cases.append(case)
       return these_cases, other_cases

    @classmethod
    def create(cls, owner, **k):
	"""Creates and returns a new case."""
        case = cls(state=CASE_STATES['incomplete'], owner=owner, **k)
        case.put()
        CaseAction.make(action='Create', case=case, actor=owner)
        return case

    def submit(self, actor, notes):
	"""Submits the case for review."""
        self.state = CASE_STATES['submitted']
        self.put()
        CaseAction.make(action='Submit', case=self, actor=actor, notes=notes)

    def review(self, approver):
	"""Assigns the case for review by the given approver."""
	previous_reviewer = self.reviewer
	if previous_reviewer == approver:
	    # case was already under review by the given approver, no-op
	    return
	# reviewer assignment or change requires actual action, state change
        self.state = CASE_STATES['under_review']
	self.put()
	CaseAction.make(action='Review', case=self, actor=approver)

    def approve(self, actor, notes):
	"""Marks the case as approved."""
        self.state = CASE_STATES['approved']
        self.put()
        CaseAction.make(action='Approve', case=self, actor=actor, notes=notes)

    def comment(self, actor, notes):
	"""Returns the case to the applicant requesting changes."""
        self.state = CASE_STATES['needs_work']
        self.put()
        CaseAction.make(action='Comment', case=self, actor=actor, notes=notes)

    @property
    def visible_state(self):
	"""Returns the display form of this case's state."""
        return self.state[3:]

    @property
    def latest_action(self):
	"""Returns the latest action recorded on this case."""
        return CaseAction.query_by_case(self).order('-timestamp').get()

    @property
    def last_modified(self):
	"""Returns the timestamp at which this case was last modified."""
        return datetime.datetime.now() - self.latest_action.timestamp

    @property
    def applicant_can_edit(self):
	"""True iff an applicant can currently modify this case."""
        return self.state in APPLICANT_EDITABLE

    @property
    def reviewer(self):
       """Returns the case's current reviewer, or None."""
       if self.state != CASE_STATES['under_review']:
           return None
       return CaseAction.query_by_case(self, 'Review').get().actor

    @property
    def submit_blockers(self):
        """Returns a list of the reasons the case may not yet be submitted (an
          empty list if the case may be submitted).
        """
        blockers = []
        for purpose in PURPOSES:
            if not self.get_document(purpose):
                blockers.append('Missing %s' % purpose)
        return blockers

    def get_document(self, purpose):
	"""Returns the document from this case for the given purpose."""
        q = CaseAction.query_by_case(self, 'Update').filter('purpose =', purpose)
        return q.get()


class CaseAction(JurisModel):
    """Immutable once fully created (by the `make` classmethod)."""
    action = db.StringProperty(required=True, choices=CASE_ACTIONS)
    case = db.ReferenceProperty(Case, required=True)
    actor = db.ReferenceProperty(User, required=True)
    purpose = db.StringProperty(required=False, choices=PURPOSES)
    notes = db.TextProperty(required=False)
    upload = blobstore.BlobReferenceProperty(required=False)

    def json(self):
        """Return JSON-serializable form."""
	d = {'cls': 'Action', 'case': self.case.json(), 'actor': self.actor.json()}
	if self.purpose:
	    d['purpose'] = self.purpose
	if self.notes:
	    d['notes'] = self.notes
	if self.upload:
	    d['upload'] = str(self.upload.key())
	d['timestamp'] = self.timestamp.isoformat()
	return d

    @classmethod
    def make(cls, **k):
	"""Create and put an action, and log information about it."""
	# TODO: send info about the action to the latrop
        logging.info('********** ')
        logging.info('********** NEW ACTION: %s', k)
        logging.info('********** JSON: %r',
	             simplejson.dumps(k, skipkeys=True, cls=ModelEncoder))
        logging.info('********** ')
        action = cls(**k)
	action.put()

    @classmethod
    def query_by_case(cls, case, action=None):
        """Returns a db.Query for actions on the given case. If action is not None,
	   only actions of the given kind are involved. The query is ordered by
	   reverse timestamp (i.e., more recent actions first).
	"""
        q = cls.all().filter('case = ', case)
	if action is not None:
	    q.filter('action = ', action)
	return q.order('-timestamp')

    @classmethod
    def upload_document_action(cls, case, purpose, user, blob_info, notes):
	"""Create and put an action of uploading a document and/or notes."""
        cls.make(action='Update', case=case, actor=user, purpose=purpose,
	         notes=notes, upload=blob_info)

    @property
    def download_url(self):
	"""URL for downloading this action's document, or empty string if none."""
        if not self.upload:
            return ''
        return '/document/serve/%s/%s' % (
            urllib.quote(str(self.upload.key())),
            urllib.quote(self.upload.filename))
