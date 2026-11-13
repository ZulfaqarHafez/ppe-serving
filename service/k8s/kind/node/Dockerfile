# SANDBOX-SPECIFIC kind node image: kindest/node with runc wrapped so negative
# oom_score_adj values are clamped to 0 (see runc-wrapper.sh). On a normal
# host, use kindest/node:v1.33.1 directly and drop `image:` from cluster.yaml.
#   docker build -t ppe-kind-node:v1.33.1 k8s/kind/node
FROM kindest/node:v1.33.1@sha256:050072256b9a903bd914c0b2866828150cb229cea0efe5892e2b644d5dd3b34f
RUN mv /usr/local/sbin/runc /usr/local/sbin/runc.real
COPY runc-wrapper.sh /usr/local/sbin/runc
RUN chmod 0755 /usr/local/sbin/runc
