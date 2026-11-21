FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public/ /usr/share/nginx/html/
# Single source of truth: tests/fixtures/pages, passed in as the `fixtures` build context
# (compose.yaml, additional_contexts). Served at /eval-fixtures/<name>.html.
COPY --from=fixtures . /usr/share/nginx/html/eval-fixtures/
