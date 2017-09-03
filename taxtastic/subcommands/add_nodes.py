# This file is part of taxtastic.
#
#    taxtastic is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    taxtastic is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with taxtastic.  If not, see <http://www.gnu.org/licenses/>.
"""Add new nodes to a database

The input file must specify new nodes in yaml format. For example:

Note order dependency

"""

import sys
import logging
import sqlalchemy

import yaml
from fastalite import Opener

from taxtastic.taxonomy import Taxonomy
from taxtastic.utils import add_database_args

log = logging.getLogger(__name__)


def build_parser(parser):
    parser = add_database_args(parser)
    parser.add_argument('new_nodes', metavar='FILE', type=Opener('r'),
                        help='yaml file specifying new nodes')
    parser.add_argument(
        '--source-name', dest='source_name',
        help=("""Provides the default source name for new nodes.  The
              value is overridden by "source_name" in the input
              file. If not provided, "source_name" is required in each
              node or name definition. This source name is created if
              it does not exist."""))


def action(args):
    engine = sqlalchemy.create_engine(args.url, echo=args.verbosity > 2)
    tax = Taxonomy(engine, schema=args.schema)

    records = list(yaml.load_all(args.new_nodes))

    log.info('adding new nodes')
    for rec in records:
        try:
            record_type = rec.pop('type')
            if record_type not in {'node', 'name'}:
                raise ValueError
        except (KeyError, ValueError):
            log.error(('error in record for tax_id {tax_id}: "type" is '
                       'required and must be one of "node" or "name"').format(**rec))
            sys.exit(1)

        if record_type == 'node':
            rec['source_name'] = rec.get('source_name') or args.source_name
            log.info(
                'new *node* with tax_id "{tax_id}", rank "{rank}"'.format(**rec))
            tax.add_node(**rec)
        elif record_type == 'name':
            for name in rec['names']:
                name['tax_id'] = rec['tax_id']
                # source_name may be provided at the record or name level
                name['source_name'] = (name.get('source_name') or
                                       rec.get('source_name') or
                                       args.source_name)
                log.info(
                    'new *name* for tax_id "{tax_id}": "{tax_name}"'.format(**name))
                tax.add_name(**name)

    engine.dispose()
