from flask import Blueprint, jsonify
from ...blueprints.api import datasource_bp
from .constants import NEWSPAPERS

newspaper_bp = Blueprint('newspaper', __name__, url_prefix='/newspaper')
datasource_bp.register_blueprint(newspaper_bp)

@newspaper_bp.route('/lookups/newspaperSlug', methods=['GET'])
def plugin_newspaper_slugs():
	lookup = list(map(lambda x: { "name": x['name'], "value": x['slug'] }, NEWSPAPERS))
	return jsonify(lookup)
