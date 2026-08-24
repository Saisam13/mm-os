# Handoff files

Every build agent writes one file here before it finishes. Nothing counts as done without it.

    a1-identity.md   a2-tokens.md   a3-shell.md
    a4-integration.md a5-servicedesk.md a6-infra.md
    b1-assembly.md   b2-retrofit.md b3-hardening.md

Sections, in this order:

    ## Delivered            what exists now, file by file
    ## Deviations           where it departed from the docs, and why
    ## Contract objections  frozen-file problems it did NOT fix
    ## Assumptions          decisions a human should confirm
    ## Not done             what was left, and what it blocks
    ## How to verify        exact commands, expected output

Read `## Contract objections` and `## Assumptions` between the two runs. Those two sections
are the whole point of this directory.
