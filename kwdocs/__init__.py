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
    flask-kwdocs
    ~~~~~~~~~~~~

    A LaTeX document management system for Flask.

    :Copyright: © 2013–2015, Chris Warrick.
    :License: BSD (see /LICENSE).
"""

from __future__ import unicode_literals

__title__ = 'Flask-KwDocs'
__version__ = '0.1.0'
__author__ = 'Chris Warrick'
__license__ = '3-clause BSD'
__docformat__ = 'restructuredtext en'

from kwlh import app, db
from flask import (Blueprint, request, flash, render_template,
                   redirect, url_for, make_response)
from flask.ext.login import login_required
import os
import io
import shutil
import re
import redis
import rq
import json
from .tasks import render_task

KwDocs = Blueprint('KwDocs', __name__, template_folder='templates')
app.config['REDIS_URL'] = 'redis://localhost:6379/0'
redisdb = redis.StrictRedis.from_url(app.config['REDIS_URL'])
q = rq.Queue(name='kwdocs', connection=redisdb)


class Document(db.Model):

    """A model for documents."""

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(512), unique=True)
    title = db.Column(db.String(512))
    author = db.Column(db.String(512))
    date = db.Column(db.String(512))

    def __init__(self, slug, title, author, date):
        """Initialize the Document object."""
        self.slug = slug
        self.title = title
        self.author = author
        self.date = date

    def __repr__(self):
        """Provide a reproduction."""
        return '<Document {0}>'.format(self.slug)


def _fetch_from_file(slug):
    """Fetch metadata from file in a hacky way."""
    data = {'title': '', 'author': '', 'date': ''}
    with io.open(os.path.join(app.config['DOCPATH'], slug, slug + '.tex'), encoding='utf-8') as fh:
        for line in fh:
            m = re.match(r'\\([a-zA-Z]*){(.*)}', line, flags=re.UNICODE)
            if (m and m.groups()[0] in ('title', 'author', 'date') and
                    m.groups()[1] != ''):
                data.update({m.groups()[0]: m.groups()[1]})

    return data


@KwDocs.route("/")
@login_required
def doclist():
    """List all the documents."""
    docs = Document.query.all()
    docsd = {d.slug: d for d in docs}
    fs = os.listdir(app.config['DOCPATH'])
    fs.remove('__ARCHIVE')
    docs = []

    for d in docsd:
        if d not in fs:
            _ = docsd[d]
            _.status = 0b10
            docs.append(_)

    for f in fs:
        if f in docsd:
            _ = docsd[f]
            _.status = 0b11
            docs.append(_)
        else:
            _ = Document(f, '', '', '')
            _.status = 0b01
            docs.append(_)

    return render_template('doclist.html', docs=docs, title='Documents', permalink=url_for('.doclist'))


@KwDocs.route("/<slug>/")
@login_required
def doc(slug):
    """Show one document."""
    doc = Document.query.filter_by(slug=slug).first()
    return render_template('doc.html', doc=doc, title='Document {0}'.format(doc.title), permalink=url_for('.doc', slug=slug))


@KwDocs.route("/<slug>/reload/")
@login_required
def reload(slug):
    """Reload document metadata."""
    try:
        d = _fetch_from_file(slug)
    except:
        flash('This document does not exist in the FS.', 'error')
        return redirect(url_for('.doc', slug=slug))

    doc = Document.query.filter_by(slug=slug).first()
    if doc:
        doc.title = d['title']
        doc.author = d['author']
        doc.date = d['date']
    else:
        doc = Document(slug, d['title'], d['author'], d['date'])
    db.session.add(doc)
    db.session.commit()
    return redirect(url_for('.doc', slug=slug))


@KwDocs.route("/__bulk__/reload/")
@login_required
def bulk_reload():
    """Reload all the metadata."""
    status = {}
    newdocs = {}
    dbd = Document.query.all()
    dbdocs = {d.slug: d for d in dbd}
    fsdocs = os.listdir(app.config['DOCPATH'])
    fsdocs.remove('__ARCHIVE')
    for f in fsdocs:
        if f in dbdocs:
            fsdocs.remove(f)

    docs = dbdocs.keys() + fsdocs

    for slug in docs:
        try:
            data = _fetch_from_file(slug)
        except:
            status[slug] = 0b01
            db.session.delete(dbdocs[slug])

        if slug in dbdocs:
            dbdocs[slug].title = data['title']
            dbdocs[slug].author = data['author']
            dbdocs[slug].date = data['date']
            status[slug] = 0b11
        else:
            newdocs[slug] = Document(slug,
                                     data['title'],
                                     data['author'],
                                     data['date'])
            status[slug] = 0b10

    for d in dbdocs.values() + newdocs.values():
        db.session.add(d)

    db.session.commit()
    flash('Documents reloaded successfully.', 'success')
    return redirect(url_for('.doclist'))


@KwDocs.route("/<slug>/view/")
@login_required
def view(slug):
    """View a PDF."""
    try:
        with open(os.path.join(app.config['DOCPATH'], slug, slug + '.pdf'),
                  'rb') as fh:
            resp = make_response(fh.read(), 200)
        resp.headers['Content-Type'] = 'application/pdf'
        return resp
    except IOError:
        flash('The PDF does not exist.', 'error')
        return redirect(url_for('.doc', slug=slug))

@KwDocs.route('/<slug>/render.json')
@login_required
def api_render(slug):
    """Rebuild the site (internally)."""
    r1_job = q.fetch_job('{0}.r1'.format(slug))
    r2_job = q.fetch_job('{0}.r2'.format(slug))

    if not r1_job and not r2_job:
        r1_job = q.enqueue_call(
            func=render_task, args=(app.config['REDIS_URL'],
                                    app.config['DOCPATH'], slug),
            job_id='{0}.r1'.format(slug))
        r2_job = q.enqueue_call(
            func=render_task, args=(app.config['REDIS_URL'],
                                    app.config['DOCPATH'], slug),
            job_id='{0}.r2'.format(slug), depends_on=r1_job)

    d = json.dumps({'1': r1_job.meta, '2': r2_job.meta})

    if ('status' in r1_job.meta and
            r1_job.meta['status'] is not None
            and 'status' in r2_job.meta and
            r2_job.meta['status'] is not None):
        rq.cancel_job('build', redisdb)
        rq.cancel_job('orphans', redisdb)

    return d


@KwDocs.route("/<slug>/render/")
@login_required
def render(slug):
    """Render a document."""
    r1_job = q.fetch_job('{0}.r1'.format(slug))
    r2_job = q.fetch_job('{0}.r2'.format(slug))

    if not r1_job and not r2_job:
        r1_job = q.enqueue_call(
            func=render_task, args=(app.config['REDIS_URL'],
                                    app.config['DOCPATH'], slug),
            job_id='{0}.r1'.format(slug))
        r2_job = q.enqueue_call(
            func=render_task, args=(app.config['REDIS_URL'],
                                    app.config['DOCPATH'], slug),
            job_id='{0}.r2'.format(slug), depends_on=r1_job)

    return render_template('render.html', slug=slug, title='Rendering {0}'.format(slug), permalink=url_for('.render', slug=slug))


@KwDocs.route("/<slug>/delete/", methods=['GET', 'POST'])
@login_required
def delete(slug):
    """Delete a document."""
    if request.method == 'POST':
        if request.form['del'] == '1':
            doc = Document.query.filter_by(slug=slug).first()
            try:
                if doc:
                    db.session.delete(doc)
                    db.session.commit()
                else:
                    flash('Removal from DB failed — no such object.', 'error')
            except:
                flash('Removal from DB failed.', 'error')
            try:
                os.rename(os.path.join(app.config['DOCPATH'], slug, slug
                                       + '.tex'),
                          os.path.join(app.config['DOCPATH'],
                                       '__ARCHIVE', slug + '.tex'))
            except:
                flash('Archiving {0}.tex failed.'.format(slug), 'error')

            try:
                shutil.rmtree(os.path.join(app.config['DOCPATH'], slug))
            except:
                flash('Directory removal failed.', 'error')
            return redirect(url_for('.doclist', slug=slug), 302)
        else:
            return redirect(url_for('.doc', slug=slug), 302)
    else:
        return render_template('delete.html', slug=slug, title='Deleting {0}'.format(slug), permalink=url_for('.delete', slug=slug))


@KwDocs.route("/<slug>/act/", methods=['POST'])
@login_required
def act(slug):
    """Redirect actions."""
    if slug == '__bulk__':
        act = '.bulk_' + request.form['act']
    else:
        act = '.' + request.form['act']

    try:
        if slug == '__bulk__':
            return redirect(url_for(act), 302)
        else:
            return redirect(url_for(act, slug=slug), 302)
    except:
        if request.form['act'] == 'dbadd':
            try:
                d = _fetch_from_file(slug)
            except:
                flash('This document does not exist in the FS.', 'error')
            else:
                doc = Document(slug, d['title'], d['author'], d['date'])
                db.session.add(doc)
                db.session.commit()
            finally:
                return redirect(url_for('.doclist'))
        elif request.form['act'] == 'dbdel':
            doc = Document.query.filter_by(slug=slug).first()
            db.session.delete(doc)
            db.session.commit()
            return redirect(url_for('.doclist'))
        else:
            return 'ERROR: invalid action {0}'.format(act)


@KwDocs.route("/__new__/", methods=['GET', 'POST'])
@login_required
def new_doc():
    """Creating a new document."""
    if request.method == 'GET' or request.form.get('act') != 'create':
        return render_template('new.html', title='New document', permalink=url_for('.new_doc'))
    else:
        slug = request.form['slug'].strip()
        src = os.path.join(app.config['DOCPATH'], 'template', 'template.tex')
        dstdir = os.path.join(app.config['DOCPATH'], slug)
        dst = os.path.join(dstdir, slug + '.tex')
        try:
            os.mkdir(dstdir)
            shutil.copy(src, dst)
        except:
            flash('Failed to create new document.', 'error')
            return redirect(url_for('.new_doc'), 302)
        reload(slug)
        return redirect(url_for('.doc', slug=slug), 302)
