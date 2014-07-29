# Copyright (c) Sunlight Foundation, 2014
# Authors:
#    - Paul R. Tagliamonte <paultag@sunlightfoundation.com>
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


from django.core.paginator import Paginator, EmptyPage
from restless.modelviews import ListEndpoint, DetailEndpoint
from restless.models import serialize
from restless.http import HttpError, Http200
from collections import defaultdict


def dout(obj):
    """
    Helper function to ensure that we're always printing internal
    datetime objects in a fully qualified UTC timezone. This will
    let 'None' values pass through untouched.
    """
    if obj is None:
        return
    return pytz.UTC.localize(obj).isoformat()


def sfilter(obj, blacklist):
    """
    Helper function to deep copy a dict, and pop elements off.
    """
    ret = copy.deepcopy(obj)
    for el in blacklist:
        ret.pop(el)
    return ret


def get_field_list(model, without=None):
    if without is None:
        without = set()
    else:
        without = set(without)
    return list(set(model._meta.get_all_field_names()) - without)


def get_fields(root, fields):
    def fwrap(obj, memo=None):
        memo = memo if memo else set()
        id_ = id(obj)
        if id_ in memo:
            return None
        memo.add(id_)

        if isinstance(obj, dict):
            if obj == {} or obj.get("fields"):
                return obj
            obj = list(filter(
                lambda x: x[1] != None,
                [(x, fwrap(y, memo=memo)) for x, y in obj.items()]
            ))
            if obj == []:
                return None
            return {"fields": obj}
        return obj
    subfields = defaultdict(list)
    concrete = []
    for field in fields:
        if '.' not in field:
            concrete.append(field)
            continue
        prefix, postfix = field.split(".", 1)
        subfields[prefix].append(postfix)
    ret = {x: fwrap(root[x]) for x in concrete}
    for key, fields in subfields.items():
        ret[key] = get_fields(root[key], fields)
    return fwrap(ret)


def cachebusterable(fn):
    def _(self, request, *args, **kwargs):
        params = request.params
        if '_' in params:
            params.pop("_")
        return fn(self, request, *args, **kwargs)
    return _


class PublicListEndpoint(ListEndpoint):
    methods = ['GET']
    per_page = 100
    serialize_config = {}
    default_fields = []

    def adjust_filters(self, params):
        return params

    def filter(self, data, **kwargs):
        kwargs = self.adjust_filters(kwargs)
        return data.filter(**kwargs)

    def sort(self, data, sort_by):
        return data.order_by(*sort_by)

    def paginate(self, data, page):
        paginator = Paginator(data, per_page=self.per_page)
        return paginator.page(page)

    @cachebusterable
    def get(self, request, *args, **kwargs):
        params = request.params
        page = 1
        if 'page' in params:
            page = int(params.pop('page'))

        sort_by = []
        if 'sort_by' in params:
            sort_by = params.pop('sort_by').split(",")

        fields = self.default_fields
        if 'fields' in params:
            fields = params.pop('fields').split(",")

        data = self.get_query_set(request, *args, **kwargs)
        data = self.filter(data, **params)
        data = self.sort(data, sort_by)
        try:
            data_page = self.paginate(data, page)
        except EmptyPage:
            raise HttpError(
                404,
                'No such page (heh, literally - its out of bounds)'
            )

        config = get_fields(self.serialize_config, fields=fields)
        response = Http200({
            "meta": {
                "count": len(data_page.object_list),
                "page": page,
                "per_page": self.per_page,
                "max_page": data_page.end_index(),
                "total_count": data.count(),
            },
            "results": [
                serialize(x, **config)
                for x in data_page.object_list
            ]
        })

        response['Access-Control-Allow-Origin'] = "*"
        return response

    @classmethod
    def get_serialize_config(cls, fields=None):
        if fields is None:
            fields = cls.default_fields
        return {"fields": [(x, cls.serialize_config[x]) for x in fields]}


class PublicDetailEndpoint(DetailEndpoint):
    methods = ['GET']

    @cachebusterable
    def get(self, request, pk, *args, **kwargs):
        params = request.params

        fields = self.default_fields
        if 'fields' in params:
            fields = params.pop('fields').split(",")

        obj = self.model.objects.get(pk=pk)
        config = get_fields(self.serialize_config, fields=fields)
        response = Http200(serialize(obj, **config))
        response['Access-Control-Allow-Origin'] = "*"

        return response
