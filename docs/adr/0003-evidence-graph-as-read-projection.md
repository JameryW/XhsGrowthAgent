# Keep the Evidence Graph as a read projection

The Creator Agent Evidence Graph will be assembled from the existing durable Creator Model, Decision Record, and Learning Signal snapshots rather than introducing a second Evidence write model. This preserves immutable decision provenance and avoids synchronization races while leaving a small repository interface that can later be replaced by a materialized graph store if query volume justifies it.
