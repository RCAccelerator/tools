# Running Tests

```
$ python openstack_parse_tempest_html_page.py --test
```
# Parsing Local Files
```
$ python openstack_parse_tempest_html_page.py tests/tempest.html
$ python openstack_parse_tempest_html_page.py tests/tempest_err.html
```

# Parsing Remote URLs


```
# passing test
$python openstack_parse_tempest_html_page.py https://11b77813494a95a1b8ad-d28bfbac581c22e8bbce39a73023702a.ssl.cf5.rackcdn.com/openstack/6596f18394bd49c1811bc56cf10b2305/testr_results.html

# failing test
$ python openstack_parse_tempest_html_page.py <downstream Zuul address>/logs/e22/components-integration/e226c33b4be0421fa516ecbb2eef3abf/logs/controller-0/ci-framework-data/tests/test_operator//tempest-tests-tempest-workflow-step-01-single-thread-testing//stestr_results.html
```
