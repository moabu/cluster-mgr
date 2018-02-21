# Changing Gluu Server hostname

Used to change a Gluu Server from one hostname to another.

```
python ldap_change_host.py -old <old_hostname> \
  -new <new_hostname> \
  -server <hostname_or_ip_of_LDAP_server> \
  -mail <email_for_certs> \
  -city <city_for_certs> \
  -state <state_for_certs> \
  -country <country_for_certs> \
  -password <ldap_pass> \
  -os <server_os>
```
  
  Let's take the example of me using `dev.example.org` but my customer changed their domain requirements to `idp.customer.io`, the environment wouldn't fit the spec and I would have to rebuild. Fortunately with this script, a quick turnaround to another hostname, with new certificates to match that domain name, is one command-line away.

  To achieve this with the previous example, I would run the command line script above inside the Gluu Server chroot like so:
  
```
python ldap_change_host.py -old dev.example.org \
  -new idp.customer.io \
  -server dev.example.org \
  -mail admin@customer.io \
  -city 'San Francisco' \
  -state CA \
  -country US \
  -password MyS3crE71D4pPas$ \
  -os Ubuntu
  ```
  
    Voila, you've successfully changed all the endpoints inside your LDAP, your Apache2/HTTPD routing, and your certificates to the new hostname. 
