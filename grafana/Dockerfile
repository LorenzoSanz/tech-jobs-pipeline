# Grafana with the jobpipe stylesheet linked from index.html.
FROM grafana/grafana-oss:11.4.0

USER root
COPY theme/jobpipe.css /usr/share/grafana/public/jobpipe.css
RUN sed -i 's#</head>#  <link rel="stylesheet" href="[[.AppSubUrl]]/public/jobpipe.css" />\n  </head>#' \
        /usr/share/grafana/public/views/index.html \
    && grep -q 'public/jobpipe.css' /usr/share/grafana/public/views/index.html
USER 472
