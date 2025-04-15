# Ansible Log Parser & RCA Submission Tool

This utility helps you extract failure-related information from Ansible log files and send it to an RCAccelerator API endpoint for further processing or analysis.

```
./ansible_log_parser.py /path/to/logs extracted_errors.txt
./send_to_rca.py extracted_errors.txt https://<rca-endpoint>/prompt
```

or

```
./extract_subunit2html_failures.py /path/to/Unit\ Test\ Report.html /tmp/errors
./send_to_rca.py /tmp/errors/test_autoscaling.txt https://<rca-endpoint>/prompt
```
