# Odoo 17 image with the NN Fund Management module baked in.
FROM odoo:17.0

# Run package install / copies as root, then drop back to the odoo user.
USER root

# Custom configuration.
COPY ./config/odoo.conf /etc/odoo/odoo.conf

# Bundle the module so the image is self-contained. For live development the
# docker-compose file also bind-mounts the same path so edits are picked up
# without rebuilding.
COPY ./nn_fund_management /mnt/extra-addons/nn_fund_management

RUN chown -R odoo:odoo /mnt/extra-addons

USER odoo
