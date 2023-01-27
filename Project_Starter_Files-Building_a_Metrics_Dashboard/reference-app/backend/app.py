# import libraries
from flask import Flask, render_template, request, jsonify, json
from prometheus_flask_exporter import PrometheusMetrics
import pymongo
from flask_pymongo import PyMongo
from os import getenv
import logging

from flask_opentracing import FlaskTracing
from jaeger_client import Config
from jaeger_client.metrics.prometheus import PrometheusMetricsFactory
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
import opentracing

# Define the Jaeger host which is referenced in the yaml file
JAEGER_HOST = getenv("JAEGER_HOST", "localhost")
# Define the app
app = Flask(__name__)

app.config["MONGO_DBNAME"] = "example-mongodb"
app.config[
    "MONGO_URI"
] = "mongodb://example-mongodb-svc.default.svc.cluster.local:27017/example-mongodb"
mongo = PyMongo(app)
# Expose the metrics
metrics = PrometheusMetrics(app, group_by="endpoint")
metrics.info("app_info", "Application Info", version="1.0.3")
# Register extra metrics
metrics.register_default(
    metrics.counter(
        "by_path_counter",
        "Request count by request paths",
        labels={"path": lambda: request.path},
    )
)

# Apply the same metric to all of the endpoints
endpoint_counter = metrics.counter(
    "endpoint_counter",
    "Request count by endpoints",
    labels={"endpoint": lambda: request.endpoint},
)

# Define the tracer
def init_tracer(service):
    logging.getLogger("").handlers = []
    logging.basicConfig(format="%(message)s", level=logging.DEBUG)

    config = Config(
        config={
            "sampler": {
                "type": "const",
                "param": 1,
            },
            "logging": True,
            "local_agent": {"reporting_host": JAEGER_HOST},
        },
        service_name=service,
		validate=True,
        metrics_factory=PrometheusMetricsFactory(service_name_label=service),
    )

    # this call also sets opentracing.tracer
    return config.initialize_tracer()

FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

#tracing initial
tracer = init_tracer("backend")
flask_tracer = FlaskTracing(tracer , True, app)

@app.route("/")
@endpoint_counter
def homepage():
    with tracer.start_span("hello-world"):
        message = "Hello World"
    return message


@app.route("/api")
@endpoint_counter
def my_api():
    with tracer.start_span("api"):
        answer = "something"
    return jsonify(repsonse=answer)


# Healthcheck status
@endpoint_counter
@app.route("/status")
def healthcheck():
    response = app.response_class(
        response=json.dumps({"result": "OK - healthy"}),
        status=200,
        mimetype="application/json",
    )
    app.logger.info("Status request successfull")
    return response


# This will return an error
@app.route("/star", methods=["POST"])
@endpoint_counter
def add_star():
    parent_span = flask_tracer.get_span()
    with opentracing.tracer.start_span('add star', child_of=parent_span) as span:
        try:
            star = mongo.db.stars
            name = request.json["name"]
            distance = request.json["distance"]
            star_id = star.insert({"name": name, "distance": distance})
            new_star = star.find_one({"_id": star_id})
            output = {"name": new_star["name"], "distance": new_star["distance"]}
            span.set_tag("output", output)
            return jsonify({"result": output})
        except:
            span.set_tag("output", "issue with database connection on star endpoint")


@app.route("/error")
@endpoint_counter
def oops():
    return ":(", 500


if __name__ == "__main__":
    app.run()
