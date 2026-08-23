# AI incident response

## Triage

An AI incident includes harmful output, data exposure, repeated unsupported answers, security abuse, or a material quality regression. Record the time, affected version, sample inputs and outputs, user impact, and reporter contact.

## Containment

For severe incidents, disable the affected feature or roll back to the last stable version. Revoke exposed credentials immediately. Preserve logs according to the retention policy without copying sensitive content into public issue trackers.

## Follow-up

The owner completes root-cause analysis, adds a regression test, documents corrective action, and obtains release approval before restoring the feature. Share a blameless summary with affected stakeholders.

