# -*- encoding: utf-8 -*-
#
# Copyright © 2014 eNovance
#
# Authors: Julien Danjou <julien@danjou.info>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import functools

import iso8601
import pecan
from pecan import rest
import voluptuous

from gnocchi.openstack.common import jsonutils
from gnocchi.openstack.common import timeutils
from gnocchi import storage


def vexpose(schema, *vargs, **vkwargs):
    def expose(f):
        f = pecan.expose(*vargs, **vkwargs)(f)

        @functools.wraps(f)
        def callfunction(*args, **kwargs):
            params = jsonutils.loads(pecan.request.body)
            try:
                schema(params)
            except voluptuous.Error as e:
                pecan.abort(400, "Invalid input: %s" % e)
            return f(*args, body=params, **kwargs)
        return callfunction
    return expose


def Timestamp(v):
    # TODO(jd) Support Unix timestamp?
    return iso8601.parse_date(v)


class EntityController(rest.RestController):
    _custom_actions = {
        'measures': ['POST', 'GET']
    }

    def __init__(self, entity_name):
        self.entity_name = entity_name

    Measures = voluptuous.Schema([{
        voluptuous.Required("timestamp"):
        Timestamp,
        voluptuous.Required("value"): voluptuous.Any(float, int),
    }])

    @vexpose(Measures)
    def post_measures(self, body):
        try:
            pecan.request.storage.add_measures(
                self.entity_name,
                (storage.Measure(
                    m['timestamp'],
                    m['value']) for m in body))
        except storage.EntityDoesNotExist as e:
            pecan.abort(400, str(e))
        # NOTE(jd) Until https://bugs.launchpad.net/pecan/+bug/1311629 is fixed
        pecan.response.status = 204

    @pecan.expose('json')
    def get_measures(self, start=None, stop=None, aggregation='mean'):
        if aggregation not in storage.AGGREGATION_TYPES:
            pecan.abort(400, "Invalid aggregation value %s, must be one of %s"
                        % (aggregation, str(storage.AGGREGATION_TYPES)))

        try:
            # Replace timestamp keys by their string versions
            return dict((timeutils.strtime(k), v)
                        for k, v in pecan.request.storage.get_measures(
                            self.entity_name,
                            start, stop, aggregation).iteritems())
        except storage.EntityDoesNotExist as e:
            pecan.abort(400, str(e))

    Entity = voluptuous.Schema({
        voluptuous.Required('archives'):
        voluptuous.All([voluptuous.All([int],
                                       voluptuous.Length(min=2, max=2))],
                       voluptuous.Length(min=1))
    })

    @vexpose(Entity, 'json')
    def post(self, body):
        # TODO(jd) Use policy to limit what values the user can use as
        # 'archive'?
        # TODO(jd) Use a better format than (seconds,number of metric)
        try:
            pecan.request.storage.create_entity(self.entity_name,
                                                body['archives'])
        except storage.EntityAlreadyExists as e:
            pecan.abort(400, str(e))
        try:
            pecan.request.indexer.create_entity(self.entity_name)
        except storage.EntityAlreadyExists as e:
            # Cancel creation
            try:
                pecan.request.storage.delete_entity(self.entity_name)
            except Exception:
                # If it fails at this point, too bad, but ignore
                pass
            pecan.abort(400, str(e))
        return {"entity": self.entity_name,
                "archives": body['archives']}

    @pecan.expose()
    def delete(self):
        try:
            pecan.request.storage.delete_entity(self.entity_name)
        except storage.EntityDoesNotExist as e:
            pecan.abort(400, str(e))
        pecan.request.indexer.delete_entity(self.entity_name)
        # NOTE(jd) Until https://bugs.launchpad.net/pecan/+bug/1311629 is fixed
        pecan.response.status = 204


class EntitiesController(rest.RestController):
    @staticmethod
    @pecan.expose()
    def _lookup(name, *remainder):
        return EntityController(name), remainder


class V1Controller(object):
    entity = EntitiesController()


class RootController(object):
    v1 = V1Controller()

    @staticmethod
    @pecan.expose(content_type="text/plain")
    def index():
        return "Nom nom nom."
