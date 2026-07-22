# Split Shot authority with Placement Commitment and Reveal

Each Player is sole authority for answering Shots against their own Board; the Relay never resolves hits. On lock-in, a Player publishes a Placement Commitment (hash of a canonical Placement) so the layout is sealed before firing. On sink, that Ship's cells are Revealed; at Match end, the full Placement is Revealed — both checked against the Commitment (and prior answers). Reveal verification is exercised in the play ticket; this ADR locks the authority and timing model.
