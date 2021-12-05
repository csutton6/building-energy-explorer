import json
import logging

from flask import Flask, request, render_template
from sqlalchemy import create_engine
from sqlalchemy.sql import text
import geopandas as gpd
import pandas as pd
import numpy as np

from bokeh.plotting import figure
from bokeh.embed import components
from bokeh.resources import CSSResources, JSResources
from bokeh.models import Span

from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure

bokeh_css = CSSResources(mode="cdn", version="2.2.3", minified=True)
bokeh_js = JSResources(mode="cdn", version="2.2.3", minified=True)

# load credentials from a file
with open("pg-credentials.json", "r") as f_in:
    pg_creds = json.load(f_in)

# mapbox
with open("mapbox_token.json", "r") as mb_token:
    MAPBOX_TOKEN = json.load(mb_token)["token"]

application = Flask(__name__, template_folder="templates")
Kate  = 'kate'

# load credentials from JSON file
HOST = pg_creds["HOST"]
USERNAME = pg_creds["USERNAME"]
PASSWORD = pg_creds["PASSWORD"]
DATABASE = pg_creds["DATABASE"]
PORT = pg_creds["PORT"]

def get_sql_engine():
    return create_engine(f"postgresql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}")

def get_neighborhood_names():
    """Gets all neighborhoods for NYC"""
    engine = get_sql_engine()
    query = text(
        """
        SELECT DISTINCT "NTA"
        FROM buildings
        ORDER BY 1 ASC
    """
    )
    resp = engine.execute(query).fetchall()
    # get a list of names
    names = [row["NTA"] for row in resp]
    return names

def get_boroughs():
    """ Gets all boroughs of New York """
    engine = get_sql_engine()
    query = text(
        """
        SELECT DISTINCT "Borough"
        FROM buildings
        ORDER BY 1 ASC
        """
    )
    resp= engine.execute(query).fetchall()
    boroughs= [row["Borough"] for row in resp]
    return boroughs


def get_prop_types():
    """Gets all the property types in the dataset"""
    engine= get_sql_engine()
    query = text("""
        SELECT DISTINCT "PrimaryPropertyType" as use_type, count(*)
        FROM buildings
        GROUP BY "PrimaryPropertyType"
        ORDER BY 2 DESC
    """)
    resp= engine.execute(query).fetchall()
    uses= [row['use_type'] for row in resp]
    return uses

def build_plot():
    img=io.StringIO()


# for index page
@application.route("/")
def index():
    """Index page"""
    names = get_neighborhood_names()
    boroughs = get_boroughs()
    prop_types = get_prop_types()
    return render_template(
        "landing.html", 
        nnames=names, 
        bboroughs=boroughs, 
        pprops = prop_types, 
        plot_html=make_opening_chart())

def get_bounds(geodataframe):
    """returns list of sw, ne bounding box pairs"""
    bounds = geodataframe.geom.total_bounds
    bounds = [[bounds[0], bounds[1]], [bounds[2], bounds[3]]] #could this be relevant
    return bounds

def get_neighborhood_buildings(nname):
    """Get all buildings for a neighborhood"""
    engine = get_sql_engine()
    buildings_response = text(
        """
        SELECT
            "Address1" as address,
            "PrimaryPropertyType" as primary_use,
            "SourceEUI" as source_eui,
            "geometry" as geom
        FROM buildings
        WHERE "NTA" = :nname
        ORDER BY 3 DESC
    """
    )
    # render query using sqlalchemy templating
    # Note: geopandas doesn't have safe escaping like sqlalchemy does
    rendered_query = buildings_response.bindparams(nname=nname).compile(
        bind=engine, compile_kwargs={"literal_binds": True}
    )
    buildings = gpd.read_postgis(rendered_query, con=engine)
    return buildings

# def get_borough_buildings(bborough):
#     """Get all the buildings for a borough"""
#     engine=get_sql_engine()
#     buildings_borough = text(
#         """
#         SELECT 
#             "Address1" as address,
#             "PrimaryPropertyType" as primary_use,
#             "SourceEUI" as source_eui,
#             "geometry" as geom
#         FROM buildings
#         WHERE "Borough" = :bborough
#         ORDER BY 3 DESC
#         """
#     )

# render query using sqlalchemy templating
    # Note: geopandas doesn't have safe escaping like sqlalchemy does
    # rendered_query = buildings_response.bindparams(bborough=bborough).compile(
    #     bind=engine, compile_kwargs={"literal_binds": True}
    # )
    # buildings = gpd.read_postgis(rendered_query, con=engine)
    # return buildings

def get_buildings_by_type(pprop):
    """Gets all buildings of a particular property type"""
    engine = get_sql_engine()
    response_3 = text(
        """
        SELECT
            "Address1" as address,
            "PropertyName" as prop_name,
            "SourceEUI" as source_eui,
            "WaterUseIntensity" as water_intensity,
            "TotalGHGEmissionsMetricTonsCO2" as ghg_emissions,
            "geometry" as geom
        FROM buildings
        WHERE "PrimaryPropertyType" = :pprop
        ORDER BY 3 DESC
    """
    )
    # render query using sqlalchemy templating
    # Note: geopandas doesn't have safe escaping like sqlalchemy does
    rendered_query = response_3.bindparams(pprop=pprop).compile(
        bind=engine, compile_kwargs={"literal_binds": True}
    )
    buildings_bytype = gpd.read_postgis(rendered_query, con=engine)
    return buildings_bytype

def get_benchmark(pprop):
    """Gets the benchmark source_eui for a property type"""
    engine = get_sql_engine()
    response = text(
        """
        SELECT
            "use_type" as prop_type,
            "benchmark" as benchmark
        FROM benchmarks
        WHERE "use_type" = :pprop
    """
    )
    # render query using sqlalchemy templating
    # Note: geopandas doesn't have safe escaping like sqlalchemy does
    rendered_query = response.bindparams(pprop=pprop).compile(
        bind=engine, compile_kwargs={"literal_binds": True}
    )
    benchmark = pd.read_sql(rendered_query, con=engine)
    benchmark = benchmark.benchmark.values[0]
    return benchmark

def count_buildings_by_type():
    """Gets a dataframe of the prevalence of each property type in the dataset"""
    engine=get_sql_engine()
    response=text(
        """
        SELECT DISTINCT "PrimaryPropertyType" as use_type, count(*)
        FROM buildings
        GROUP BY "PrimaryPropertyType"
        ORDER BY 2 DESC
        LIMIT 15
        """
    )
    rendered_query=response.bindparams().compile(bind=engine, compile_kwargs={"literal_binds": True})
    grouped_types = pd.read_sql(rendered_query, con=engine)
    return grouped_types

def make_building_chart(pprop, benchmark):
    """Make a bar chart of number of buildings by description"""
    buildings = get_buildings_by_type(pprop)

    plot = figure(plot_width = 400, plot_height = 300,
        title='Distribution of Energy Intensity Scores',
        toolbar_location=None,
        tools="",
        tooltips=[('Energy Intensity', "@bpttom"), ("Count", "@top")],
        x_axis_label = 'Energy Intensity (kBtu/sq.ft.)', y_axis_label = 'Count of Buildings')

    hist, edges = np.histogram(buildings['source_eui'], density=True, bins=50)    
    
    logging.warning(str(buildings))
    plot.quad(top=hist, bottom=0, left=edges[:-1], right=edges[1:], line_color="white")
    vline = Span(location=benchmark, dimension='height', line_color='red', line_width=3)
    plot.renderers.extend([vline])


    script, div = components(plot)
    kwargs = {"script": script, "div": div, "js_files": bokeh_js.js_files, "pprop": pprop}
    return render_template("html_plot.html", **kwargs)

# @app.route("/energyviewer", methods=["GET"])
# def energy_viewer():
#     """Test for form"""
#     name = request.args["neighborhood"] # where does this reference; does it need a .get?
#     borough = request.args['borough']
#     buildings = get_neighborhood_buildings(name)
#     bounds = get_bounds(buildings)

#     # generate interactive map
#     map_html = render_template(
#         "geojson_map.html",
#         geojson_str=buildings.to_json(),
#         bounds=bounds,
#         center_lng=(bounds[0][0] + bounds[1][0]) / 2,
#         center_lat=(bounds[0][1] + bounds[1][1]) / 2,
#         mapbox_token=MAPBOX_TOKEN,
#     )
#     return render_template(
#         "explorer.html",
#         nname=name,
#         map_html=map_html,
#         buildings=buildings[["address", "primary_use", "source_eui"]].values,
#     )

def make_opening_chart():
    """Make a bar chart of number of buildings by description"""
    grouped_types = count_buildings_by_type()

    plot = figure(
        plot_width = 500, 
        plot_height = 450,
        title='Most Frequent Property Types in the Dataset',
        x_range=grouped_types['use_type'],
        toolbar_location=None,
        tools="",
        tooltips=[('Property Type', "@x"), ("Count", "@top")],
        x_axis_label = 'Property Type', y_axis_label = 'Count of Buildings')
    
    logging.warning(str(grouped_types))
    plot.vbar(x=grouped_types['use_type'], top=grouped_types['count'], width=0.8)

    plot.xgrid.grid_line_color = None
    plot.y_range.start = 0
    plot.xaxis.major_label_orientation = 45


    script, div = components(plot)
    kwargs = {"script": script, "div": div, "js_files": bokeh_js.js_files}
    return render_template("html_plot.html", **kwargs)


@application.route("/energyviewer", methods=["GET"])
def energy_viewer_type():
    """Test for form"""
    # name = request.args["neighborhood"] # where does this reference; does it need a .get?
    # borough = request.args['borough']
    prop_type = request.args['prop_type']
    buildings = get_buildings_by_type(prop_type)
    bounds = get_bounds(buildings)
    benchmark = get_benchmark(prop_type)

    # generate interactive map
    map_html = render_template(
        "geojson_map.html",
        geojson_str=buildings.to_json(),
        bounds=bounds,
        benchmark=benchmark,
        center_lng=(bounds[0][0] + bounds[1][0]) / 2,
        center_lat=(bounds[0][1] + bounds[1][1]) / 2,
        mapbox_token=MAPBOX_TOKEN,
    )
    return render_template(
        "explorer.html",
        pprop=prop_type,
        benchmark=benchmark,
        map_html=map_html,
        plot_html = make_building_chart(prop_type, benchmark),
        buildings=buildings[["address", "prop_name", "source_eui", "water_intensity", 'ghg_emissions']].values
    )

@application.errorhandler(404)
def page_not_found(err):
    """404 page"""
    return f"404 ({err})"


if __name__ == "__main__":
    application.jinja_env.auto_reload = True
    application.config["TEMPLATES_AUTO_RELOAD"] = True
    application.run()
