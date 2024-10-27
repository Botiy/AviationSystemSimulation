import paho.mqtt.client as mqtt
import time
import json
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter, BatchSpanProcessor
from opentelemetry.trace import StatusCode, SpanContext
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource

# Set up tracing
servicename = Resource.create({"service.name": "Aircraft Automation"})
provider = TracerProvider(resource=servicename)
trace.set_tracer_provider(provider)

jaeger_exporter = JaegerExporter(
    agent_host_name='localhost',
    agent_port=6831,
)

# Configure Console Exporter
console_exporter = ConsoleSpanExporter()

# Add processors for both exporters
provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
provider.add_span_processor(SimpleSpanProcessor(console_exporter))

# Create a tracer
tracer = trace.get_tracer(__name__)

broker = "test.mosquitto.org"
subscribe_topic = "system/FlightCrew/Instructions/messageToAutomation"
publish_topic = "system/AircraftAutomation/Instructions/messageToProcesses"


#client = mqtt.Client()
#client.connect(broker)

# Set Last Will and Testament (LWT) to indicate offline status if Aircraft Automation disconnects unexpectedly
client = mqtt.Client()
client.will_set("system/AircraftAutomation/Status", payload="offline", qos=1, retain=True)

# Connect to the broker and publish an 'online' status message
client.connect(broker)
client.publish("system/AircraftAutomation/Status", payload="online", qos=1, retain=True)

def publish_message(message_code, codetype, message, qos):
    with tracer.start_as_current_span("Publish message from Aircraft Automation!") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        span_id = span.get_span_context().span_id
        message_size = len(message) + len(codetype)
        span.set_attribute("message.size", message_size)
        span.set_attribute("mqtt.broker", broker)
        span.set_attribute("mqtt.topic", publish_topic)

        timestamp = int(time.time() * 1000)

        payload = json.dumps({
            "message_code": message_code,
            "codetype": codetype,
            "message_content": message,
            "timestamp": timestamp,
            "trace_id": trace_id,
            "span_id": format(span_id, '016x')
        })
        span.set_attribute("message.content", message)
        span.set_attribute("message.timestamp", timestamp)

        result = client.publish(publish_topic, payload, qos=qos)
        span.set_attribute("mqtt.publish.result", result.rc)


        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            span.set_status(StatusCode.OK)
        else:
            span.set_status(StatusCode.ERROR)

    print(f"Forwarded message - Code: {message_code}, Type: {codetype}, Content: {message}")


def on_message(client, userdata, message):
    payload = json.loads(message.payload.decode())
    # Convert the trace_id and span_id back to integers
    trace_id = int(payload.get("trace_id"), 16)
    span_id = int(payload.get("span_id"), 16)

    # Create a new SpanContext using the trace_id and span_id
    context = trace.set_span_in_context(
        trace.NonRecordingSpan(
            SpanContext(
                trace_id=trace_id,
                span_id=span_id,
                is_remote=True,
                trace_flags=trace.TraceFlags(1),  # Set trace flags (e.g., sampled)
                trace_state=trace.TraceState(),
            )
        )
    )

    with tracer.start_as_current_span("Aircraft Automation received the message!", context=context) as span:
        received_timestamp = int(time.time() * 1000)
        published_timestamp = payload.get("timestamp")
        message_code = payload.get("message_code")
        codetype = payload.get("codetype")
        message_content = payload.get("message")

        span.set_attribute("message.received_timestamp", received_timestamp)
        span.set_attribute("message.published_timestamp", published_timestamp)
        span.set_attribute("mqtt.topic", message.topic)
        span.set_attribute("message.code", message_code)
        span.set_attribute("message.codetype", codetype)
        span.set_attribute("message.content", message_content)
        print(f"Received message: {message_content}")

        # Forward the message
        if message_code == 11 and codetype == "INSTRUCTION":
            transformed_message = "Increasing engine performance!"
            publish_message(111, "AUTOMATION", transformed_message, qos=1)

        elif message_code == 21 and codetype == "NO OPERATION":
            transformed_message = "All systems operational, waiting for instructions!"
            publish_message(211, "AUTOMATION", transformed_message, qos=1)

        elif message_code == 31 and codetype == "INSTRUCTION":
            transformed_message = "Autopilot mode engaged!"
            publish_message(311, "AUTOMATION", transformed_message, qos=1)

        elif message_code == 41 and codetype == "INSTRUCTION":
            transformed_message = "Manual control activated."
            publish_message(411, "AUTOMATION", transformed_message, qos=1)

        else:
            # Forward the message unchanged if no transformation is required
            publish_message(message_code, codetype, message_content, qos=1)


client.on_message = on_message
client.subscribe(subscribe_topic, qos=1)

client.loop_forever()