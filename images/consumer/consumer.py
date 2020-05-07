import os
import pika
import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(level=logging.INFO)

config.load_incluster_config()
kube_api = client.BatchV1Api()

conn = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq', port=5672))
chan = conn.channel()
chan.queue_declare(queue='jobs', durable=True)

registry = os.environ['REGISTRY']


def create_job(routine_id, extension):
    """Fill job as per routine.yaml content."""
    # Create job base object
    job = client.V1Job(api_version='batch/v1', kind='Job')
    # Fill with metadata
    job.metadata = client.V1ObjectMeta(name=routine_id)
    # Prepare template object
    job.spec = client.V1JobSpec(
        template=client.V1PodTemplateSpec(
            spec=client.V1PodSpec(
                containers=[client.V1Container(
                    name=routine_id,
                    image="%s/%s" % (registry, routine_id),
                    args=["wrapper.py", routine_id, extension]
                )],
                restart_policy='Never'
            )
        ),
        backoff_limit=4
    )
    return job


def callback(channel, method, properties, body):
    body = body.decode('utf-8')
    routine_id, extension = "|".join(body.split("|")[:-1]), body.split("|")[-1]
    logging.info("Received id %s, extension %s" % (routine_id, extension))
    # TODO: only create if resource check is correct (query loadbalancer)
    job = create_job(routine_id, extension)
    try:
        res = kube_api.create_namespaced_job('default', job)
        logging.info("Created")
        logging.debug(res)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except ApiException as exception:
        logging.error("Could not create job: %s" % exception)


if __name__ == '__main__':
    chan.basic_consume(
        queue='jobs',
        on_message_callback=callback
    )
    chan.start_consuming()
