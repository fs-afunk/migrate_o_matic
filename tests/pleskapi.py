import plesk.apiclient

web3 = plesk.apiclient.Client(host='web3.firstscribe.com', verbose=False)
success = web3.lookup_plesk_info()

site_id = web3.get_site_id('novushc.com')

if success:
    records = web3.get_dns_records(site_id)
    template = web3.get_dns_template()
    #
    # for record in records:
    #     del record['id']

    print(template)
    for d in template:
        d['host'] = d['host'].replace('<domain>', 'novushc.com').replace('<ip>', '216.185.198.100')
        d['value'] = d['value'].replace('<domain>', 'novushc.com').replace('<ip>', '216.185.198.100')
        d['site-id'] = site_id


    print(template)

    diffs = [x for x in records if x not in template]
    for diff in diffs:
        print(diff)


