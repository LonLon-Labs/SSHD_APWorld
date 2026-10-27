//! "Bird Statues Give Items" locations.
//!
//! Detection no longer happens in the client. Like decoupled Goddess Cubes, the
//! game itself watches each statue's flag (`handle_bird_statue_items` in
//! `rust-additions/src/item.rs`) and, when a statue is touched, gives the item
//! stored for it with the normal item-get animation (or as a real trap actor).
//! It then sets the location's AP custom flag, which `CustomFlagPoller` already
//! reports as a location check like every other custom-flag location.
//!
//! All the client has to do is know which locations are given natively, so that
//! own-world items from them are not delivered a second time through the item
//! buffer when the server echoes them back (see `DeliveryTracker::set_native_locations`).

use std::collections::HashSet;

/// AP location code of the first Bird Statue location. The 26 statues use the
/// contiguous codes `FIRST_LOCATION_CODE..FIRST_LOCATION_CODE + LOCATION_COUNT`
/// (see `Locations.py` and `BIRD_STATUE_LOCATION_NAMES` in `stagepatchhandler.py`).
pub const FIRST_LOCATION_CODE: i64 = 2773911;
pub const LOCATION_COUNT: i64 = 26;

/// Bird Statue locations outside the contiguous block: Inside the Volcano and
/// Inside Fire Sanctuary.
pub const EXTRA_LOCATION_CODES: [i64; 2] = [2774485, 2774486];

/// The AP location codes of all Bird Statue locations.
pub fn location_codes() -> HashSet<i64> {
    let mut codes: HashSet<i64> = (FIRST_LOCATION_CODE..FIRST_LOCATION_CODE + LOCATION_COUNT).collect();
    codes.extend(EXTRA_LOCATION_CODES);
    codes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn covers_all_28_statue_locations() {
        let codes = location_codes();
        assert_eq!(codes.len(), 28);
        assert!(codes.contains(&2774485));
        assert!(codes.contains(&2774486));
        assert!(codes.contains(&2773911));
        assert!(codes.contains(&2773936));
    }
}
