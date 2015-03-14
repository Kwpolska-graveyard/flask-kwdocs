#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Flask-KwDocs v0.2.0
# A LaTeX document management system for Flask.
# Copyright © 2013–2015, Chris Warrick.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions, and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions, and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the author of this software nor the names of
#    contributors to this software may be used to endorse or promote
#    products derived from this software without specific prior written
#    consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
    flask-kwdocs.tasks
    ~~~~~~~~~~~~~~~~~~

    Tasks for KwDocs.

    :Copyright: © 2013–2015, Chris Warrick.
    :License: BSD (see /LICENSE).
"""

# This is based on code from Coil CMS, using components © 2015, Chris Warrick.

from __future__ import unicode_literals

import subprocess
import os
from rq import get_current_job
from redis import StrictRedis


def render_task(dburl, docpath, slug):
    """Render a document."""
    oldcwd = os.getcwd()
    try:
        os.chdir(os.path.join(docpath, slug))
    except:
        db = StrictRedis.from_url(dburl)
        job = get_current_job(db)
        job.meta.update({'out': 'Document not found.', 'return': 127, 'status': False})
        return 127

    db = StrictRedis.from_url(dburl)
    job = get_current_job(db)
    job.meta.update({'out': '', 'milestone': 0, 'total': 1, 'return': None,
                     'status': None})
    job.save()

    p = subprocess.Popen(('lualatex', '--halt-on-error', slug + '.tex'),
                         stdout=subprocess.PIPE)

    out = []

    while p.poll() is None:
        nl = p.stdout.readline()
        out.append(nl)
        job.meta.update({'out': ''.join(out), 'return': None,
                         'status': None})
        job.save()

    out = ''.join(out)
    job.meta.update({'out': ''.join(out), 'return': p.returncode, 'status':
                     p.returncode == 0})
    job.save()
    os.chdir(oldcwd)
    return p.returncode
