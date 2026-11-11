# Grafana with the jobpipe stylesheet linked from index.html.
FROM grafana/grafana-oss:11.4.0

USER root
COPY theme/jobpipe.css /usr/share/grafana/public/jobpipe.css
# ?v= is a hash of the stylesheet, so browsers fetch it again whenever it changes.
RUN version=$(md5sum /usr/share/grafana/public/jobpipe.css | cut -c1-10) \
    && sed -i "s#</head>#  <link rel=\"stylesheet\" href=\"[[.AppSubUrl]]/public/jobpipe.css?v=${version}\" />\n  </head>#" \
        /usr/share/grafana/public/views/index.html \
    && grep -q "public/jobpipe.css?v=${version}" /usr/share/grafana/public/views/index.html
USER 472
