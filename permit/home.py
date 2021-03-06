# -*- coding: utf-8 -*-
"""
    home
    ~~~~~~~~~~~~~~~~~~~~

    Handlers for the home page, including login/registration flow.

    :copyright: 2011 by Google, Inc.
    :license: Apache 2.0, see LICENSE for more details.
"""
from tipfy.app import Response
from tipfy.handler import RequestHandler
from tipfy.sessions import SessionMiddleware
from tipfyext.jinja2 import Jinja2Mixin
import config
import models


class HomeHandler(RequestHandler, Jinja2Mixin):
    middleware = [SessionMiddleware()]

    def get(self):
        """Home Page, assumes no state!."""
        # Get user from session or CGI params.
        if self.request.args.get('logout'):
            email = None
            if 'email' in self.session:
                del self.session['email']
        else:
            email = self.request.args.get('email', None)
            if email:
                # set email in session
                self.session['email'] = email
            else:
                # try to get email from session
                email = self.session.get('email', None)

        if email:
            user = models.User.get_by_email(email)
            if not user:
                user = models.User(email=email)
                user.put()

        else:
            user = None

        if user:
            role = self.request.args.get('role', None)
            if role:
                user.role = role
                user.put()

            if user.role == 'Applicant':
                return self.redirect('/applicant/home')
            if user.role == 'Permit Approver':
                return self.redirect('/approver/home')

        context = {
            'user': user,
            'roles': models.USER_ROLES,
        }
        context.update(config.config)

        return self.render_response('home.html', **context)
