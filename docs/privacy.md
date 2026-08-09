# Privacy

Simura is **self-hosted software**. You run it on your
own machine or infrastructure, and this policy describes how it handles data.

## No data collection

Simura does **not** collect analytics, telemetry, or personal data, and it does
**not** phone home. The dashboard talks only to the twin core **you** run; neither
sends data to Simura or any third party.

## Your data stays in your deployment

Battery telemetry, system specifications you build, and any datasets you upload
for validation live entirely within your own deployment — your MQTT broker, your
TimescaleDB, your instance. Simura has no access to it.

## Uploaded datasets

Files you upload for validation (`/api/validation/upload`) are parsed **in memory
to a temporary file that is deleted immediately after the run**. They are not
stored, indexed, or transmitted anywhere.

## Third-party services

Simura makes no outbound network calls of its own. If you follow links in the
app (documentation, dataset homepages) or download an external dataset, those
third-party sites have their own privacy practices, which this policy does not
cover.

## Contact

Questions about this policy can be raised as an issue on the project repository.
